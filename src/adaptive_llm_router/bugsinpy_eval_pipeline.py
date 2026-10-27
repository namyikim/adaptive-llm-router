"""Opt-in one-case L2/L3 candidate generation + independent Docker verification.

This workflow is intentionally *not* fully blind: the six-case study uses
historically known target files and regression-test-derived symptoms.
No API or third-party tests run by default. No fixed implementation/test is
ever included in the model's input. Never infer model quality from one case.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from .bugsinpy_llm_patch_generate import PILOT, prepare, call_anthropic, extract_patch
from .bugsinpy_patch_verifier import verify_patch
from .bugsinpy_patch_compare import compare_patch_trials
from .bugsinpy_reproduce import (
    EXPECTED_COMMITS, ReplayError, checkout_versions, prepare_metadata,
)

EXPECTED_EVIDENCE_TYPE = "audited_historical_bug_reproduction_only"


def load_reviewed_symptom(evidence_path: Path, case_id: str) -> dict:
    """Only a short reported symptom; never load fixed test code/patch."""
    data = json.loads(evidence_path.read_text(encoding="utf-8"))
    if data.get("record_type") != EXPECTED_EVIDENCE_TYPE:
        raise ReplayError("Unreviewed historical reproduction evidence")
    matching = [x for x in data.get("cases", []) if x.get("id") == case_id]
    if len(matching) != 1:
        raise ReplayError("Missing/duplicate historical case evidence")
    record = matching[0]
    if record.get("status") not in (
        "log_and_machine_verified_buggy_fail_fixed_pass",
        "log_verified_buggy_fail_fixed_pass",
    ) or record.get("llm_verified_success") is not None:
        raise ReplayError("Unverified baseline or claimed LLM repair outcome")
    observations = record.get("buggy_errors")
    if not isinstance(observations, list) or not 1 <= len(observations) <= 3:
        raise ReplayError("Missing/invalid observed failure symptoms")
    if any(not isinstance(x, str) or not 5 <= len(x) <= 450 for x in observations):
        raise ReplayError("Unbounded failure descriptions")
    # These observations came from fixed-commit regression tests. They are
    # an explicit symptom oracle, but contain neither regression test code
    # nor implementation fixes. Disclosure is recorded in the report.
    symptom = "\n".join(observations)
    return {
        "case_id": case_id,
        "observation": symptom,
        "observation_sha256": hashlib.sha256(symptom.encode()).hexdigest(),
        "source_run_id": record["run_id"],
        "symptom_provenance": "fixed_commit_regression_test_observation_oracle",
    }


def run_pipeline(*, case_id: str, dataset_root: Path, workspace: Path,
                 evidence_path: Path, output_root: Path,
                 l2_model: str = "", l3_model: str = "",
                 allow_paid_api: bool = False, execute_patch_tests: bool = False,
                 max_tokens: int = 4096) -> dict:
    if case_id not in PILOT:
        raise ValueError("Initial pipeline only supports tqdm-6 or tornado-6")
    if not 256 <= max_tokens <= 8192:
        raise ValueError("max_tokens must be between 256 and 8192")
    if execute_patch_tests and not allow_paid_api:
        raise ValueError("Cannot execute patches without explicit paid-mode opt-in")
    if output_root.exists() and any(output_root.iterdir()):
        raise ReplayError("Output folder must be empty; GitHub job reruns may still incur new API charges")
    if allow_paid_api:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ValueError("ANTHROPIC_API_KEY secret missing")
        if not l2_model or not l3_model or l2_model == l3_model:
            raise ValueError("Explicit distinct L2/L3 provider model IDs required")

    baseline = prepare_metadata(dataset_root, case_id)
    if baseline["buggy_commit"] != EXPECTED_COMMITS[case_id][0]:
        raise ReplayError("Wrong pinned historical buggy commit")
    evidence = load_reviewed_symptom(evidence_path, case_id)
    sources = checkout_versions(baseline, workspace / "source")
    candidate_input = prepare(case_id, sources["buggy"], evidence["observation"])
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "prompt.txt").write_text(candidate_input["prompt"], encoding="utf-8")

    report = {
        "kind": "opt_in_single_case_llm_patch_evaluation",
        "case_id": case_id,
        "buggy_commit": baseline["buggy_commit"],
        "prompt_sha256": candidate_input["input_sha256"],
        "symptom_provenance": evidence["symptom_provenance"],
        "symptom_sha256": evidence["observation_sha256"],
        "historical_run_id": evidence["source_run_id"],
        "target_file_provenance": "historical_fix_location_oracle",
        "paid_api_enabled": bool(allow_paid_api),
        "patch_tests_enabled": bool(execute_patch_tests),
        "results": {"l2": {"status": "not_requested", "verified_patch_success": None},
                    "l3": {"status": "not_requested", "verified_patch_success": None}},
        "comparison": {"status": "not_measured"},
        "notes": [
            "Historical known target file and test-derived symptom are oracle-assisted.",
            "No official fixing implementation or verifier-only test code sent to LLM.",
            "One selected case cannot estimate overall routing accuracy or cost savings.",
        ],
    }
    summary_path = output_root / "e2e_summary.json"

    def save():
        summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")

    save()
    if not allow_paid_api:
        report["status"] = "dry_run_no_api_no_patch_tests"
        save()
        return report

    for tier, model_id in (("l2", l2_model), ("l3", l3_model)):
        row = {
            "requested_model": model_id,
            "generation_status": "not_started",
            "verified_patch_success": None,
        }
        report["results"][tier] = row
        save()
        try:
            answer = call_anthropic(
                candidate_input["prompt"], model_id,
                os.environ["ANTHROPIC_API_KEY"], max_tokens)
            # Preserve real usage/latency even if the model returned unusable text.
            row.update({
                "reported_model": answer["model"],
                "response_id": answer["id"],
                "usage": answer["usage"],
                "generation_latency_ms": answer["elapsed_ms"],
                "usd_cost": None,  # No guessed tariffs or unverified USD.
            })
            save()
            patch = extract_patch(answer["answer"], case_id)
            patch_name = tier + ".diff"
            (output_root / patch_name).write_bytes(patch)
            row.update({
                "generation_status": "candidate_generated",
                "patch_file": patch_name,
                "patch_sha256": hashlib.sha256(patch).hexdigest(),
                "status": "patch_not_tested",
            })
            save()
            if execute_patch_tests:
                # Separate workspaces allow identical L2/L3 patches to be
                # independently tested without stale-directory collisions.
                verification = verify_patch(
                    dataset_root=dataset_root,
                    workspace=workspace / ("verify_" + tier),
                    output_root=output_root / "verifier_results",
                    case_id=case_id, tier=tier, model_id=model_id,
                    patch_file=output_root / patch_name,
                    model_latency_ms=row["generation_latency_ms"],
                    execute=True,
                )
                if verification.get("patch_sha256") != row["patch_sha256"]:
                    raise ReplayError("Candidate SHA mismatch between generation and verifier")
                row["verification_file"] = (
                    "verifier_results/" + case_id + "_" + tier + ".json")
                row["verified_patch_success"] = verification["regression_passed"]
                row["status"] = verification["status"]
        except Exception as exc:
            # Never hide the other tier's results; no network retries.
            # Avoid leaking API headers or credentials in saved errors.
            row["status"] = "generation_or_verification_error"
            row["error_type"] = type(exc).__name__
        save()

    if execute_patch_tests:
        # The existing six-case comparator never imputes missing trials.
        # With one requested case, the other five remain explicitly incomplete.
        six_case = compare_patch_trials(output_root / "verifier_results")
        (output_root / "six_case_comparison.json").write_text(
            json.dumps(six_case, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        report["six_case_comparison_file"] = "six_case_comparison.json"
        report["overall_six_case_success_rates"] = six_case["overall_six_case_success_rates"]
    observed = [report["results"][tier]["verified_patch_success"] for tier in ("l2", "l3")]
    if all(isinstance(x, bool) for x in observed):
        report["comparison"] = {
            "status": "both_independently_verified_one_case",
            "l2_passed": observed[0], "l3_passed": observed[1],
            "quality_conclusion": "insufficient_sample_to_rank_models",
        }
    else:
        report["comparison"] = {"status": "insufficient_or_unverified_outcomes"}
    report["status"] = "pipeline_finished_review_artifacts"
    save()
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--case-id", required=True, choices=PILOT)
    p.add_argument("--dataset-root", required=True, type=Path)
    p.add_argument("--workspace", required=True, type=Path)
    p.add_argument("--evidence-file", required=True, type=Path)
    p.add_argument("--output-root", required=True, type=Path)
    p.add_argument("--l2-model", default="")
    p.add_argument("--l3-model", default="")
    p.add_argument("--max-tokens", type=int, default=4096)
    p.add_argument("--allow-paid-api", action="store_true")
    p.add_argument("--execute-patch-tests", action="store_true")
    args = p.parse_args()
    report = run_pipeline(
        case_id=args.case_id, dataset_root=args.dataset_root,
        workspace=args.workspace, evidence_path=args.evidence_file,
        output_root=args.output_root, l2_model=args.l2_model,
        l3_model=args.l3_model, max_tokens=args.max_tokens,
        allow_paid_api=args.allow_paid_api,
        execute_patch_tests=args.execute_patch_tests)
    print(json.dumps({
        "status": report["status"], "case_id": report["case_id"],
        "l2": report["results"]["l2"]["status"],
        "l3": report["results"]["l3"]["status"],
        "comparison": report["comparison"]["status"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
