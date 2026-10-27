"""CI audit of real pinned source and one archived candidate; no paid calls.

Reads already checked-out public sources. Does not execute their Python code,
apply a patch, rewrite candidate hunks, or alter previous experiment results.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

BUGGY = "a4b9c86db548b2d0dbb5af7a6bbdc26ab47e1eec"
CANDIDATE = "474de3de40565605b4c4f1d9a01ad498d1a85ab409961f8880f1a12a3d8863ec"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--buggy-root", type=Path, required=True)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    args = p.parse_args()
    summary = json.loads((args.results / "e2e_summary.json").read_text())
    manifest = json.loads((args.results / "source_manifest.json").read_text())
    prompt = (args.results / "prompt.txt").read_text(encoding="utf-8")
    source = subprocess.check_output(["git", "-C", str(args.buggy_root),
                                      "show", BUGGY + ":tqdm/_tqdm.py"], timeout=30)
    assert summary["source_context_version"] == "full-pinned-files-v2"
    assert summary["paid_api_enabled"] is False
    assert summary["patch_tests_enabled"] is False
    assert len(manifest) == 1 and manifest[0]["complete"] is True
    assert manifest[0]["source_sha256"] == hashlib.sha256(source).hexdigest()
    assert source.decode("utf-8") in prompt
    assert "        if disable:\n" in prompt
    assert "original file line numbers" in prompt
    definitions = {x["name"]: x for x in manifest[0]["definitions"]}
    assert "tqdm.__init__" in definitions and "tqdm.__len__" in definitions
    candidate_bytes = args.candidate.read_bytes()
    assert hashlib.sha256(candidate_bytes).hexdigest() == CANDIDATE
    before = (args.buggy_root / "tqdm/_tqdm.py").read_bytes()
    result = subprocess.run(["git", "-C", str(args.buggy_root), "apply", "--check",
                             "--", str(args.candidate.resolve())],
                            capture_output=True, timeout=30)
    assert (args.buggy_root / "tqdm/_tqdm.py").read_bytes() == before
    assert args.candidate.read_bytes() == candidate_bytes
    audit = {
        "audit_type": "complete_source_and_original_candidate_applicability_only",
        "source_commit": BUGGY, "source_manifest": manifest,
        "prompt_bytes": len(prompt.encode("utf-8")),
        "missing_disable_branch_now_present": True,
        "original_candidate_sha256": CANDIDATE,
        "original_candidate_apply_check_returncode": result.returncode,
        "original_candidate_apply_check_stderr": result.stderr.decode("utf-8", errors="replace")[:8192],
        "source_and_candidate_unchanged": True,
        "paid_api_calls": 0, "candidate_regression_test_executed": False,
        "candidate_regression_passed": None,
    }
    (args.results / "source_and_saved_candidate_audit.json").write_text(
        json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in audit.items() if key != "source_manifest"}, indent=2))
    print("Complete source lines:", manifest[0]["line_count"])
    print("Original constructor:", definitions["tqdm.__init__"])
    print("Original length method:", definitions["tqdm.__len__"])


if __name__ == "__main__":
    main()
