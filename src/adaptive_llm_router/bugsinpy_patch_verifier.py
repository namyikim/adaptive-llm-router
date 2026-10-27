"""Offline, independent regression verifier for external L2/L3 patch candidates.

Does NOT call a model or infer success from missing test evidence.
Untrusted candidate source executes only inside capped offline Docker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .bugsinpy_reproduce import (
    ALLOWED_CASES, REGRESSION_TEST_FILES, REPRODUCED, ReplayError,
    checkout_versions, classify_reproduction, docker_test, prepare_metadata,
)

MAX_PATCH_BYTES = 32768
MAX_CHANGED_FILES = 5
_ALLOWED_HEADER = re.compile(r"^diff --git a/([A-Za-z0-9_./-]+) b/([A-Za-z0-9_./-]+)$")
_ALLOWED_INDEX = re.compile(r"^index [0-9a-f]{7,64}\.\.[0-9a-f]{7,64}(?: 100644)?$")
_ALLOWED_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@(?: .*)?$")
_REPORT_STATUSES = {"not_executed", "patch_rejected", "baseline_not_reproduced",
                    "regression_passed", "regression_failed", "inconclusive", "patch_apply_failed"}


class CandidatePatchError(ValueError):
    pass


def read_candidate_patch(path: Path, case_id: str) -> tuple[bytes, list[str]]:
    """Gate existing production-only Python edits; git apply checks applicability."""
    if case_id not in ALLOWED_CASES:
        raise CandidatePatchError("Unknown benchmark case")
    if not path.is_file() or path.is_symlink():
        raise CandidatePatchError("Patch file must be a regular file")
    size = path.stat().st_size
    if size == 0 or size > MAX_PATCH_BYTES:
        raise CandidatePatchError("Patch file is empty or exceeds 32 KiB")
    raw = path.read_bytes()
    if b"\x00" in raw:
        raise CandidatePatchError("Binary patch not accepted")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise CandidatePatchError("Patch must be UTF-8") from exc
    changed = []
    section = 0
    saw_minus = saw_plus = saw_hunk = False
    for line in lines:
        if line.startswith("diff --git "):
            if section and not (saw_minus and saw_plus and saw_hunk):
                raise CandidatePatchError("Incomplete previous diff section")
            match = _ALLOWED_HEADER.fullmatch(line)
            if not match or match.group(1) != match.group(2):
                raise CandidatePatchError("Only same-path modifications allowed")
            name = match.group(1)
            root = "tqdm" if case_id.startswith("tqdm-") else "tornado"
            bits = name.split("/")
            if (len(bits) < 2 or bits[0] != root or not name.endswith(".py")
                    or any(b in (".", "..", "", "tests", "test", "__pycache__") for b in bits)
                    or name in changed or name.endswith("/conftest.py") or name.endswith("/setup.py")):
                raise CandidatePatchError("Patch may modify only production Python sources")
            changed.append(name)
            if len(changed) > MAX_CHANGED_FILES:
                raise CandidatePatchError("Too many modified files")
            section += 1
            saw_minus = saw_plus = saw_hunk = False
        elif not section:
            raise CandidatePatchError("Expected diff --git header first")
        elif line.startswith("index "):
            if not _ALLOWED_INDEX.fullmatch(line):
                raise CandidatePatchError("Unsupported index or file mode")
        elif line.startswith("--- "):
            if line != "--- a/" + changed[-1] or saw_minus or saw_hunk:
                raise CandidatePatchError("Unexpected old file header")
            saw_minus = True
        elif line.startswith("+++ "):
            if line != "+++ b/" + changed[-1] or not saw_minus or saw_plus:
                raise CandidatePatchError("Unexpected new file header")
            saw_plus = True
        elif line.startswith("@@ "):
            if not saw_plus or not _ALLOWED_HUNK.fullmatch(line):
                raise CandidatePatchError("Invalid unified diff hunk")
            saw_hunk = True
        elif saw_hunk and (line.startswith("+") or line.startswith("-")
                           or line.startswith(" ") or line == r"\ No newline at end of file"):
            continue
        else:
            raise CandidatePatchError("Unsupported diff metadata or line")
    if not changed or not (saw_minus and saw_plus and saw_hunk):
        raise CandidatePatchError("Incomplete candidate patch")
    return raw, changed


def _safe_source_paths(worktree: Path, names: list[str]) -> None:
    top = worktree.resolve()
    for name in names:
        current = top
        for part in name.split("/"):
            current = current / part
            if current.is_symlink():
                raise CandidatePatchError("Symlink path is not permitted")
        if not current.is_file() or not current.resolve().is_relative_to(top):
            raise CandidatePatchError("Modified source file not present in buggy checkout")


def _test_one(image: str, source: Path, command: list[str], verifier: Path,
              logs: Path, name: str) -> dict:
    row = docker_test(image, source, command, regression_test_from_fixed=verifier)
    output = row.pop("output")
    log_name = name + ".log"
    (logs / log_name).write_text(output, encoding="utf-8")
    row["log_file"] = log_name
    row["test_origin"] = "fixed_commit_regression_test_for_verifier_only"
    return row


def _all_pass(rows: list[dict]) -> bool:
    return bool(rows) and all(x["verdict"] == "pass" for x in rows)


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _diagnostic_text(value) -> str:
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    if not isinstance(text, str):
        return ""
    # Only local git stdout/stderr, never provider exceptions, HTTP headers or env.
    return "".join(c for c in text[:8192] if c in "\n\t" or ord(c) >= 32)


def _apply_step(tree: Path, patch_file: Path, output_root: Path,
                case_id: str, tier: str, check_only: bool) -> dict:
    stage = "patch_apply_check" if check_only else "patch_apply"
    command = ["git", "-C", str(tree), "apply"]
    if check_only:
        command.append("--check")
    command.extend(["--", str(patch_file.resolve())])
    try:
        result = subprocess.run(command, capture_output=True, check=True, timeout=30)
        code, stdout, stderr = 0, result.stdout, result.stderr
    except subprocess.CalledProcessError as exc:
        code, stdout, stderr = exc.returncode, exc.stdout, exc.stderr
    log_name = f"{case_id}_{tier}_{stage}.log"
    log_root = output_root / "logs"
    log_root.mkdir(exist_ok=True)
    (log_root / log_name).write_text(
        f"stage={stage}\nreturncode={code}\nstdout:\n{_diagnostic_text(stdout)}\n"
        f"stderr:\n{_diagnostic_text(stderr)}\n", encoding="utf-8")
    return {"stage": stage, "returncode": code, "log_file": "logs/" + log_name}


def verify_patch(*, dataset_root: Path, workspace: Path, output_root: Path,
                 case_id: str, tier: str, model_id: str, patch_file: Path | None,
                 execute: bool = False, model_cost_usd: float | None = None,
                 model_latency_ms: float | None = None) -> dict:
    if case_id not in ALLOWED_CASES or tier not in ("l2", "l3"):
        raise ValueError("Selected case/tier is not on the allowlist")
    if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 128:
        raise ValueError("Explicit, nonblank model_id required")
    if execute and model_id.strip() == "pending-model":
        raise ValueError("Real external target-model identity required before testing")
    for name, value in (("model_cost_usd", model_cost_usd), ("model_latency_ms", model_latency_ms)):
        if value is not None and (isinstance(value, bool) or
                not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0):
            raise ValueError(name + " must be an observed nonnegative number")
    output_root.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1, "evaluation": "independent_candidate_patch_regression_only",
        "case_id": case_id, "tier": tier, "model_id": model_id,
        "status": "not_executed", "executed": False, "candidate_test_executed": False,
        "llm_called_by_verifier": False, "regression_passed": None, "full_bugfix_certified": False,
        "verifier_test_origin": "fixed_commit_verifier_only_not_model_input",
        "model_cost_usd_observed": model_cost_usd, "model_latency_ms_observed": model_latency_ms,
        "limitations": "Regression-test-only. No full suite or L1 coverage. "
                       "A missing or unverified candidate is not counted as failure or success.",
    }
    out = output_root / f"{case_id}_{tier}.json"
    if patch_file is None or not patch_file.is_file():
        report["status"] = "awaiting_candidate_patch"
        _save(out, report)
        return report
    try:
        raw, changed = read_candidate_patch(patch_file, case_id)
        report["patch_sha256"] = hashlib.sha256(raw).hexdigest()
        report["modified_files"] = changed
    except (CandidatePatchError, OSError) as exc:
        report["status"] = "patch_rejected"
        report["validation_error"] = str(exc)[:300]
        _save(out, report)
        return report
    if not execute:
        _save(out, report)
        return report

    record = prepare_metadata(dataset_root, case_id)
    report["expected_buggy_commit"] = record["buggy_commit"]
    report["expected_fixed_commit_for_verifier_only"] = record["fixed_commit_for_verifier_only"]
    report["executed"] = True
    working_tree = None
    source_repo = None
    stage = "environment_preflight"
    try:
        subprocess.run(["docker", "image", "inspect", record["docker_image"]],
                       capture_output=True, check=True, timeout=30)
        stage = "source_checkout"
        sources = checkout_versions(record, workspace)
        verifier_test = sources["fixed"] / REGRESSION_TEST_FILES[case_id]
        if not verifier_test.is_file():
            raise ReplayError("Pinned verifier-only regression test does not exist")
        report["verifier_test_sha256"] = hashlib.sha256(verifier_test.read_bytes()).hexdigest()
        log_root = output_root / "logs"
        log_root.mkdir(exist_ok=True)
        stage = "baseline_verification"
        baseline = [_test_one(record["docker_image"], sources["buggy"], command,
                              verifier_test, log_root, f"{case_id}_{tier}_baseline_{i}")
                    for i, command in enumerate(record["test_commands"], 1)]
        fixed = [_test_one(record["docker_image"], sources["fixed"], command,
                           verifier_test, log_root, f"{case_id}_{tier}_fixed_{i}")
                 for i, command in enumerate(record["test_commands"], 1)]
        report["baseline_tests"] = baseline
        report["fixed_tests"] = fixed
        baseline_status = classify_reproduction(baseline, fixed)
        report["baseline_verification_status"] = baseline_status
        if baseline_status != REPRODUCED:
            report["status"] = "baseline_not_reproduced"
            return report

        stage = "candidate_worktree"
        source_repo = (workspace / "repos" / record["project"]).resolve()
        scratch = Path(tempfile.mkdtemp(prefix="candidate_patch_", dir=workspace.resolve()))
        working_tree = scratch / "src"
        subprocess.run(["git", "-C", str(source_repo), "worktree", "add",
                        "--detach", str(working_tree), record["buggy_commit"]],
                       capture_output=True, check=True, timeout=180)
        _safe_source_paths(working_tree, changed)
        for check_only in (True, False):
            stage = "patch_apply_check" if check_only else "patch_apply"
            evidence = _apply_step(working_tree, patch_file, output_root, case_id, tier, check_only)
            report.setdefault("patch_application_steps", []).append(evidence)
            report["patch_application"] = evidence
            if evidence["returncode"] != 0:
                report["status"] = "patch_apply_failed"
                report["failure_stage"] = stage
                report["error_type"] = "CalledProcessError"
                # Do not fix offsets/recount hunks or score an unexecuted patch.
                return report
        stage = "candidate_tests"
        report["candidate_test_executed"] = True
        candidate = [_test_one(record["docker_image"], working_tree, command,
                               verifier_test, log_root, f"{case_id}_{tier}_candidate_{i}")
                     for i, command in enumerate(record["test_commands"], 1)]
        report["candidate_tests"] = candidate
        report["regression_passed"] = _all_pass(candidate)
        if report["regression_passed"]:
            report["status"] = "regression_passed"
        elif any(x["verdict"] not in ("pass", "test_failure") for x in candidate):
            report["status"] = "inconclusive"
            report["regression_passed"] = None
        elif any(x["verdict"] == "test_failure" for x in candidate):
            report["status"] = "regression_failed"
        else:
            report["status"] = "inconclusive"
            report["regression_passed"] = None
    except (OSError, ReplayError, CandidatePatchError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired, ValueError) as exc:
        report["status"] = "inconclusive"
        report["failure_stage"] = stage
        report["error_type"] = type(exc).__name__
        report["regression_passed"] = None
    finally:
        try:
            if working_tree is not None and source_repo is not None and working_tree.exists():
                subprocess.run(["git", "-C", str(source_repo), "worktree", "remove", "--force", str(working_tree)],
                               capture_output=True, check=False, timeout=45)
                shutil.rmtree(working_tree.parent, ignore_errors=True)
        except (OSError, subprocess.TimeoutExpired) as exc:
            report["cleanup_error_type"] = type(exc).__name__
        finally:
            _save(out, report)
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset-root", type=Path, required=True)
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--output-root", type=Path, required=True)
    p.add_argument("--case-id", choices=ALLOWED_CASES, required=True)
    p.add_argument("--tier", choices=("l2", "l3"), required=True)
    p.add_argument("--model-id", required=True)
    p.add_argument("--patch-file", type=Path)
    p.add_argument("--model-cost-usd", type=float)
    p.add_argument("--model-latency-ms", type=float)
    p.add_argument("--execute", action="store_true", help="Run historical code only inside capped offline Docker")
    args = p.parse_args()
    result = verify_patch(dataset_root=args.dataset_root, workspace=args.workspace,
        output_root=args.output_root, case_id=args.case_id, tier=args.tier,
        model_id=args.model_id, patch_file=args.patch_file, execute=args.execute,
        model_cost_usd=args.model_cost_usd, model_latency_ms=args.model_latency_ms)
    print(json.dumps({k: result.get(k) for k in (
        "case_id", "tier", "model_id", "status", "executed", "regression_passed",
        "full_bugfix_certified", "patch_sha256", "failure_stage")}, indent=2))


if __name__ == "__main__":
    main()
