"""Paired exploratory Kev-4B vs Kev-9B decisions on identical BugsInPy inputs.

No LLM answer is generated. No verified success rate or correctness label is
claimed. Persist *each* decision promptly for Colab disconnect recovery.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
from pathlib import Path
from collections import Counter
from typing import Callable
from urllib.request import urlopen

from .analysis_router import select_analysis_model
from .routing import TIERS

MODEL_LABELS = ("kev-4b@v1.0", "kev-9b@v1.0")

class KevModelMismatch(RuntimeError):
    """The live GPU server did not attest to the expected pinned Kev checkpoint."""


def probe_model_identity(base_url: str, expected_label: str, *, timeout: float = 12.0) -> dict:
    """Validate checkpoint identity from the upstream server's actual /v1/models.run.

    Request payloads/responses saying "kev-latest" don't attest checkpoint size.
    Never infer the running model from the label assigned by the notebook.
    """
    if expected_label not in MODEL_LABELS:
        raise ValueError("Unknown checkpoint label")
    expected_run = "jaredpalmer/" + expected_label
    try:
        with urlopen(base_url.rstrip("/") + "/v1/models", timeout=timeout) as response:
            data = json.load(response)
    except (OSError, TimeoutError, ValueError) as exc:
        raise KevModelMismatch("Cannot independently identify the local Kev server") from exc
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list) or not models:
        raise KevModelMismatch("Kev /v1/models has no model cards")
    runs = {card.get("run") for card in models if isinstance(card, dict)}
    if runs != {expected_run}:
        raise KevModelMismatch(
            f"Wrong Kev server on {base_url}: expected {expected_run!r}, "
            f"reported {sorted(str(run) for run in runs)!r}"
        )
    card = models[0]
    return {
        "checkpoint_run": expected_run,
        "reported_run": card["run"],
        "base": card.get("base"),
        "device": card.get("device"),
        "backend": card.get("backend"),
        "dtype": str(card.get("dtype")) if card.get("dtype") is not None else None,
        "verified_from": "/v1/models.run",
        "verified": True,
    }



def read_cases(path: Path) -> list[dict]:
    rows, ids = [], set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not isinstance(row.get("input"), str):
            raise ValueError("Every case must have real input text")
        if row.get("source") != "BugsInPy" or row.get("task_type") not in ("code", "log"):
            raise ValueError("Expected BugsInPy code/log case")
        case_id = row.get("id")
        if not isinstance(case_id, str) or case_id in ids:
            raise ValueError("Case IDs must be unique")
        ids.add(case_id)
        rows.append(row)
    if not rows:
        raise ValueError("No cases")
    return rows


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()]


def collect_decisions(cases_path: Path, output_path: Path, model_label: str, *,
                      base_url: str = "http://127.0.0.1:8009",
                      checkpoint_callback: Callable[[], None] | None = None) -> dict:
    if model_label not in MODEL_LABELS:
        raise ValueError("Model label must identify a pinned Kev checkpoint")
    # Probe the LIVE process before writing a single row. This blocks a stale
    # Kev-9B process being silently mislabeled as Kev-4B after a failed restart.
    model_identity = probe_model_identity(base_url, model_label)
    cases = read_cases(cases_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    previous = read_rows(output_path)
    # Only previously attested rows count as complete. Historical unverified
    # decisions are re-evaluated, rather than silently treated as a valid pair.
    completed = {(r["id"], r["model_label"], r["input_sha256"]) for r in previous
                 if r.get("server_identity", {}).get("checkpoint_run") == model_identity["checkpoint_run"]
                 and r.get("server_identity", {}).get("verified") is True}
    new_successes = 0
    for case in cases:
        identity = (case["id"], model_label, case["input_sha256"])
        if identity in completed:
            continue
        start = time.perf_counter()
        try:
            decision = select_analysis_model(
                case["task_type"], case["input"], backend="kev",
                base_url=base_url, fallback_on_error=False)
            result = decision.as_dict()
            status = result["status"]
            error = None
        except (Exception) as exc:
            # Mark failures explicitly, do not turn a fallback L3 into a success.
            result, status, error = None, "failed", type(exc).__name__
        elapsed = (time.perf_counter() - start) * 1000
        row = {
            "id": case["id"],
            "model_label": model_label,
            "server_identity": model_identity,
            "input_sha256": case["input_sha256"],
            "task_type": case["task_type"],
            "log_status": case.get("log_status"),
            "status": status,
            "error_type": error,
            "decision": result,
            "end_to_end_decision_ms": round(elapsed, 3),
        }
        with output_path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            os.fsync(out.fileno())
        # Ensure each completed choice is uploaded before moving to the next case.
        if checkpoint_callback:
            checkpoint_callback()
        completed.add(identity)
        new_successes += status == "proposed"
        print(f"{model_label} {case['id']}: {status} "
              f"{result.get('tier') if result else '(no decision)'}")
    return {"model_label": model_label, "server_identity": model_identity,
            "cases": len(cases), "new_successes": new_successes,
            "output": str(output_path)}


def _mean_or_none(values: list[float]) -> float | None:
    return round(statistics.mean(values), 4) if values else None


def compare_decisions(cases: list[dict], result_rows: list[dict]) -> dict:
    inputs = {c["id"]: c["input_sha256"] for c in cases}
    latest = {}
    for row in result_rows:
        label = row.get("model_label")
        if label not in MODEL_LABELS or row.get("id") not in inputs:
            continue
        if row.get("input_sha256") != inputs[row["id"]]:
            continue  # never silently pair different inputs
        expected_run = "jaredpalmer/" + label
        if (row.get("server_identity", {}).get("checkpoint_run") != expected_run
                or row.get("server_identity", {}).get("verified") is not True):
            continue  # old/unattested/mislabeled records are not valid comparison evidence
        latest[(row["id"], label)] = row
    summaries = {}
    project_by_id = {c["id"]: c["id"].rsplit("-", 1)[0] for c in cases}
    contexts = Counter(c.get("context_mode", "fix_diff") for c in cases)
    projects = Counter(project_by_id.values())
    for label in MODEL_LABELS:
        records = [latest[(case_id, label)] for case_id in inputs
                   if (case_id, label) in latest]
        good = [r for r in records if r.get("status") == "proposed" and r.get("decision")]
        summaries[label] = {
            "n_expected": len(cases),
            "n_recorded": len(records),
            "n_successful_decisions": len(good),
            "n_failed_decisions": len(records) - len(good),
            "raw_tier_distribution": {t: sum(r["decision"]["proposed_tier"] == t for r in good) for t in TIERS},
            "selected_tier_distribution": {t: sum(r["decision"]["tier"] == t for r in good) for t in TIERS},
            "mean_max_choice_probability": _mean_or_none([r["decision"]["p_max"] for r in good]),
            "mean_model_latency_ms": _mean_or_none([
                r["decision"]["decision_latency_ms"] for r in good
                if isinstance(r["decision"].get("decision_latency_ms"), (int, float))
                and math.isfinite(r["decision"]["decision_latency_ms"])]),
            "mean_e2e_decision_ms": _mean_or_none([r["end_to_end_decision_ms"] for r in good]),
            "median_e2e_decision_ms": round(statistics.median(
                r["end_to_end_decision_ms"] for r in good), 4) if good else None,
        }
    paired = []
    for case in cases:
        a, b = (latest.get((case["id"], label)) for label in MODEL_LABELS)
        if a is None or b is None or a.get("status") != "proposed" or b.get("status") != "proposed":
            continue
        ca, cb = a.get("decision"), b.get("decision")
        if not ca or not cb:
            continue
        paired.append({
            "id": case["id"],
            "task_type": case["task_type"],
            "log_status": case.get("log_status"),
            "input_sha256": case["input_sha256"],
            "kev4_raw": ca["proposed_tier"],
            "kev9_raw": cb["proposed_tier"],
            "kev4_final": ca["tier"],
            "kev9_final": cb["tier"],
            "kev4_pmax": ca["p_max"],
            "kev9_pmax": cb["p_max"],
            "kev4_model_latency_ms": ca["decision_latency_ms"],
            "kev9_model_latency_ms": cb["decision_latency_ms"],
        })
    per_project = {}
    for project in sorted(projects):
        matching = [r for r in paired if project_by_id[r["id"]] == project]
        per_project[project] = {
            "n_input_cases": projects[project],
            "n_paired": len(matching),
            "n_raw_disagreement": sum(r["kev4_raw"] != r["kev9_raw"] for r in matching),
            "n_final_disagreement": sum(r["kev4_final"] != r["kev9_final"] for r in matching),
        }
    exact_pmax = sum(r["kev4_pmax"] == r["kev9_pmax"] for r in paired)
    vectors_equal = sum(
        latest[(r["id"], MODEL_LABELS[0])]["decision"].get("probabilities")
        == latest[(r["id"], MODEL_LABELS[1])]["decision"].get("probabilities")
        for r in paired
    )
    return {
        "evaluation": "paired_actual_buggy_source_routing_exploration",
        "identity_attestation_required": True,
        "model_identity_verified_counts": {
            label: sum(1 for r in latest.values() if r.get("model_label") == label)
            for label in MODEL_LABELS
        },
        "exact_pmax_match_count": exact_pmax,
        "exact_probability_vector_match_count": vectors_equal,
        "probability_vector_identity_warning": (
            "Every paired case has the exact same probability vector. "
            "Check independent checkpoint provenance, routing prompt and caching."
            if paired and vectors_equal == len(paired) else None
        ),
        "context_mode_distribution": dict(contexts),
        "project_case_counts": dict(sorted(projects.items())),
        "per_project_comparison": per_project,
        "n_raw_disagreement": sum(r["kev4_raw"] != r["kev9_raw"] for r in paired),
        "n_final_disagreement": sum(r["kev4_final"] != r["kev9_final"] for r in paired),
        "mean_pmax_difference_kev9_minus_kev4": _mean_or_none(
            [r["kev9_pmax"] - r["kev4_pmax"] for r in paired]),
        "n_cases": len(cases),
        "n_paired": len(paired),
        "raw_agreement_rate": (
            sum(r["kev4_raw"] == r["kev9_raw"] for r in paired) / len(paired) if paired else None
        ),
        "final_agreement_rate": (
            sum(r["kev4_final"] == r["kev9_final"] for r in paired) / len(paired) if paired else None
        ),
        "models": summaries,
        "paired_cases": paired,
        "warnings": [
            "These are real buggy Python source excerpts, but failures were NOT reproduced unless log_status is externally_supplied.",
            ("Fix-diff filename oracle used in some cases; NOT a blind benchmark." if
             contexts.get("fix_diff", 0) else
             "Only known test files from metadata were used, no fixing diff paths. "
             "Missing failure logs and issue descriptions still prevent task success scoring."),
            "No independent correctness labels or target LLM success/failure. Choice agreement and confidence are NOT routing accuracy.",
            "Speed comparisons may be affected by warm-up, CUDA state and caching; repeat randomized runs before claims.",
            "Only independently attested /v1/models.run identities are counted; legacy unverified rows are ignored.",
        ],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cases", required=True, type=Path)
    p.add_argument("--results", required=True, type=Path)
    p.add_argument("--summary", type=Path)
    p.add_argument("--model-label", choices=MODEL_LABELS)
    p.add_argument("--base-url", default="http://127.0.0.1:8009")
    args = p.parse_args()
    if args.model_label:
        print(json.dumps(collect_decisions(args.cases, args.results, args.model_label,
                                          base_url=args.base_url), ensure_ascii=False))
    if args.summary:
        report = compare_decisions(read_cases(args.cases), read_rows(args.results))
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
        print("Comparison saved:", args.summary,
              "Paired:", report["n_paired"], "/", report["n_cases"])


if __name__ == "__main__":
    main()
