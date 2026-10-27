"""Opt-in offline verification of an EXTERNALLY generated candidate patch.

No LLM/API is called. No historical fixed implementation is given to the
candidate; fixed-commit TEST files are verifier-only. Candidate source code is
untrusted: execute solely on disposable, offline, resource-capped Docker runner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from .bugsinpy_reproduce import (
    ALLOWED_CASES, REGRESSION_TEST_FILES, ReplayError, checkout_versions,
    docker_test, prepare_metadata,
)

# Frozen implementation paths identified by a separate human review of the
# historical diff. NEVER include these paths or official fixes in LLM prompts.
PATCH_TARGETS = {
    "tqdm-6": {"tqdm/_tqdm.py"},
    "tornado-5": {"tornado/ioloop.py"},
    "tornado-6": {"tornado/ioloop.py", "tornado/platform/asyncio.py"},
    "tornado-7": {"tornado/ioloop.py"},
    "tornado-11": {"tornado/http1connection.py"},
    "tornado-14": {"tornado/ioloop.py"},
}
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")
UNSAFE_HEADERS = ("GIT binary patch", "Binary files ", "new file mode",
                  "deleted file mode", "old mode ", "new mode ",
                  "rename from ", "rename to ", "copy from ", "copy to ")


def inspect_patch(data: bytes, case_id: str) -> dict:
    """Fail closed for unsafe path/mode/binary/new files; no shell operations."""
    if case_id not in ALLOWED_CASES:
        raise ValueError("Unapproved BugsInPy case")
    if not data or len(data) > 100_000 or b"\x00" in data:
        raise ReplayError("Patch missing, too large, or binary")
    try:
        source = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReplayError("Patch must be UTF-8") from exc
    if "\r" in source:
        raise ReplayError("Patch must have Unix LF lines")
    lines = source.splitlines()
    seen, changed, in_file, have_hunk = set(), [], False, False
    for ln in lines:
        if ln.startswith(UNSAFE_HEADERS) or " 160000" in ln or " 120000" in ln:
            raise ReplayError("Unsafe diff operation/mode")
        if ln.startswith("diff --git "):
            if in_file and not have_hunk:
                raise ReplayError("Diff file has no hunks")
            pieces = ln.split(" ")
            if len(pieces) != 4 or not pieces[2].startswith("a/") or not pieces[3].startswith("b/"):
                raise ReplayError("Malformed git diff header")
            old, new = pieces[2][2:], pieces[3][2:]
            if old != new or old not in PATCH_TARGETS[case_id] or old in seen:
                raise ReplayError("Candidate modifies disallowed or duplicate source path")
            if old.startswith("/") or ".." in Path(old).parts:
                raise ReplayError("Unsafe patch path")
            seen.add(old)
            changed.append(old)
            in_file, have_hunk = True, False
        elif ln.startswith("--- ") or ln.startswith("+++ "):
            if not in_file or ln[4:] not in (f"a/{changed[-1]}", f"b/{changed[-1]}"):
                raise ReplayError("Unexpected original/new file header")
            if ln.startswith("--- ") and ln[4:] != f"a/{changed[-1]}":
                raise ReplayError("Old source mismatch")
            if ln.startswith("+++ ") and ln[4:] != f"b/{changed[-1]}":
                raise ReplayError("New source mismatch")
        elif ln.startswith("@@ "):
            if not in_file or not HUNK.match(ln):
                raise ReplayError("Invalid hunk")
            have_hunk = True
        elif ln.startswith("index ") or ln.startswith("\\ No newline at end of file"):
            continue
        elif ln.startswith((" ", "+", "-")):
            if not (in_file and have_hunk):
                raise ReplayError("Patch edit occurs outside a hunk")
        elif not ln:
            continue
        else:
            raise ReplayError("Unexpected diff content")
    if not changed or not have_hunk:
        raise ReplayError("No usable patch hunks")
    return {"sha256": hashlib.sha256(data).hexdigest(),
            "changed_paths": sorted(changed), "size_bytes": len(data)}


def status_from_tests(rows: list[dict]) -> str:
    if not rows:
        return "inconclusive"
    values = [x["verdict"] for x in rows]
    if all(v == "pass" for v in values):
        return "pass"
    if any(v in ("test_not_collected", "environment_failure", "timeout",
                 "nonzero_unclassified") for v in values):
        return "inconclusive"
    return "test_failure" if "test_failure" in values else "inconclusive"


def verify_patch(record: dict, *, patch_file: Path, workspace: Path,
                 output_root: Path, execute: bool = False) -> dict:
    """Evaluate a candidate on frozen buggy commit; no paid model requests."""
    case_id = record["case_id"]
    blob = patch_file.read_bytes()
    manifest = inspect_patch(blob, case_id)
    output_root.mkdir(parents=True, exist_ok=True)
    report = {
        "case_id": case_id, "candidate": manifest,
        "buggy_commit": record["buggy_commit"],
        "verifier_test_provenance": "pinned_fixed_commit_test_only",
        "status": "not_executed", "verified_patch_success": None,
        "llm_generated": "not_verified_by_tool",
        "caveat": "Verifies an externally supplied patch, not that a specific LLM generated it.",
    }
    outfile = output_root / "candidate_patch_verification.json"
    if not execute:
        outfile.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report
    try:
        subprocess.run(["docker", "image", "inspect", record["docker_image"]],
                       capture_output=True, check=True, timeout=30)
        sources = checkout_versions(record, workspace)
        buggy_root = sources["buggy"]
        fixed_test_file = sources["fixed"] / REGRESSION_TEST_FILES[case_id]
        if not fixed_test_file.is_file():
            raise ReplayError("Verifier-only pinned regression test not present")
        report["verifier_test_sha256"] = hashlib.sha256(fixed_test_file.read_bytes()).hexdigest()

        # Copy code to a fresh disposable workspace. Never patch the original
        # source worktree; fail rather than reuse an existing candidate folder.
        temp_root = workspace / "patch_candidates" / (case_id + "-" + manifest["sha256"][:12])
        if temp_root.exists():
            raise ReplayError("Candidate working directory already exists")
        temp_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(buggy_root, temp_root, ignore=shutil.ignore_patterns(".git"),
                        symlinks=False)
        # git apply uses patch file only as data; no shell, no --unsafe-paths.
        subprocess.run(["git", "apply", "--check", "--", str(patch_file.resolve())],
                       cwd=temp_root, check=True, capture_output=True, timeout=45)
        subprocess.run(["git", "apply", "--", str(patch_file.resolve())],
                       cwd=temp_root, check=True, capture_output=True, timeout=45)
        # Readonly test bind mount overlays the patched buggy source.
        results = {"baseline_buggy": [], "candidate_patched": []}
        for group, path in (("baseline_buggy", buggy_root),
                            ("candidate_patched", temp_root)):
            for i, command in enumerate(record["test_commands"], 1):
                row = docker_test(
                    record["docker_image"], path, command,
                    regression_test_from_fixed=fixed_test_file,
                )
                logfile = f"{case_id}_{group}_{i}.log"
                (output_root / logfile).write_text(row.pop("output"), encoding="utf-8")
                row["output_file"] = logfile
                results[group].append(row)
        report["tests"] = results
        baseline = status_from_tests(results["baseline_buggy"])
        candidate = status_from_tests(results["candidate_patched"])
        report["baseline_status"] = baseline
        report["candidate_status"] = candidate
        if baseline != "test_failure":
            report["status"] = "unverified_baseline"
            report["verified_patch_success"] = None
        elif candidate == "inconclusive":
            report["status"] = "inconclusive_candidate"
            report["verified_patch_success"] = None
        else:
            report["status"] = "patch_passed" if candidate == "pass" else "patch_failed"
            report["verified_patch_success"] = candidate == "pass"
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired,
            ReplayError) as exc:
        report["status"] = "environment_or_patch_error"
        report["error_type"] = type(exc).__name__
        report["verified_patch_success"] = None
    outfile.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset-root", type=Path, required=True)
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--output-root", type=Path, required=True)
    p.add_argument("--case-id", required=True, choices=ALLOWED_CASES)
    p.add_argument("--patch-file", type=Path, required=True,
                   help="Locally supplied candidate unified diff; NEVER official fixed patch")
    p.add_argument("--execute", action="store_true",
                   help="Explicitly run untrusted patched code in bounded offline Docker")
    args = p.parse_args()
    record = prepare_metadata(args.dataset_root, args.case_id)
    result = verify_patch(record, patch_file=args.patch_file, workspace=args.workspace,
                          output_root=args.output_root, execute=args.execute)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
