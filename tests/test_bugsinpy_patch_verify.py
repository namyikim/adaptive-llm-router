"""Offline patch verifier safety/contract tests. No Docker or LLM calls."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.bugsinpy_patch_verify import (
    inspect_patch, status_from_tests, verify_patch,
)
from adaptive_llm_router.bugsinpy_reproduce import ReplayError


def diff(path="tornado/ioloop.py"):
    return ("diff --git a/{p} b/{p}\n"
            "--- a/{p}\n+++ b/{p}\n"
            "@@ -1 +1 @@\n-old line\n+new line\n").format(p=path).encode()


class CandidateVerificationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_accepts_only_reviewed_implementation_path(self):
        m = inspect_patch(diff(), "tornado-5")
        self.assertEqual(m["changed_paths"], ["tornado/ioloop.py"])
        self.assertEqual(m["size_bytes"], len(diff()))
        self.assertEqual(inspect_patch(diff("tqdm/_tqdm.py"), "tqdm-6")["changed_paths"],
                         ["tqdm/_tqdm.py"])
        with self.assertRaises(ReplayError):
            inspect_patch(diff("tornado/test/ioloop_test.py"), "tornado-5")
        with self.assertRaises(ReplayError):
            inspect_patch(diff("tornado/ioloop.py"), "tornado-11")
        with self.assertRaises(ReplayError):
            inspect_patch(diff("tornado/platform/asyncio.py"), "tornado-7")

    def test_rejects_security_sensitive_diff_constructs(self):
        bad = [
            diff("../../../etc/passwd"),
            diff(".github/workflows/tests.yml"),
            diff() + b"diff --git a/tornado/ioloop.py b/tornado/ioloop.py\n",
            b"diff --git a/tornado/ioloop.py b/tornado/ioloop.py\n"
            b"new file mode 100644\n--- /dev/null\n+++ b/tornado/ioloop.py\n@@ -0,0 +1 @@\n+x\n",
            diff().replace(b"--- a/tornado/ioloop.py", b"--- /dev/null"),
            diff().replace(b"+++ b/tornado/ioloop.py", b"+++ /dev/null"),
            diff() + b"GIT binary patch\n",
            diff() + b"\x00",
            diff() + b"\r\n",
            diff().replace(b"@@ -1 +1 @@", b"@@ junk"),
            b"",
        ]
        for case in bad:
            with self.subTest(example=case[:70]):
                with self.assertRaises(ReplayError):
                    inspect_patch(case, "tornado-5")

    def test_success_requires_true_failing_baseline_then_passing_patch(self):
        row = lambda x: {"verdict": x}
        self.assertEqual(status_from_tests([row("pass")]), "pass")
        self.assertEqual(status_from_tests([row("test_failure")]), "test_failure")
        self.assertEqual(status_from_tests([row("test_not_collected")]), "inconclusive")
        self.assertEqual(status_from_tests([row("pass"), row("timeout")]), "inconclusive")
        self.assertEqual(status_from_tests([]), "inconclusive")

    def test_default_dry_run_does_not_run_any_external_command(self):
        f = self.root / "candidate.diff"
        f.write_bytes(diff())
        rec = {"case_id": "tornado-5", "buggy_commit": "a" * 40}
        with patch("adaptive_llm_router.bugsinpy_patch_verify.subprocess.run",
                   side_effect=AssertionError("external commands disabled")), \
             patch("adaptive_llm_router.bugsinpy_patch_verify.checkout_versions",
                   side_effect=AssertionError("historical sources disabled")):
            out = verify_patch(
                rec, patch_file=f, workspace=self.root / "work",
                output_root=self.root / "results",
            )
        self.assertEqual(out["status"], "not_executed")
        self.assertIsNone(out["verified_patch_success"])
        self.assertEqual(out["llm_generated"], "not_verified_by_tool")
        self.assertEqual(json.loads(
            (self.root / "results/candidate_patch_verification.json").read_text()
        )["status"], "not_executed")


if __name__ == "__main__":
    unittest.main()
