"""CPU-only tests for missing-test classification and verifier-only test backport."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.bugsinpy_reproduce import (
    REPRODUCED, ReplayError, classify_reproduction, docker_test, run_one,
)


class BackportTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def test_missing_test_never_counts_as_bug_failure(self):
        p = subprocess.CompletedProcess(
            args=[], returncode=4, stdout="collected 0 items\n",
            stderr="ERROR: not found: /src/tqdm/tests/tests_synchronisation.py::test_imap",
        )
        with patch("adaptive_llm_router.bugsinpy_reproduce.subprocess.run",
                   return_value=p):
            out = docker_test("adaptive-bugsinpy:py36", self.root, [
                "python", "-m", "pytest",
                "tqdm/tests/tests_synchronisation.py::test_imap",
            ])
        self.assertEqual(out["verdict"], "test_not_collected")
        self.assertEqual(
            classify_reproduction([out], [{"verdict": "pass"}]),
            "environment_or_timeout",
        )

    def test_backport_mounts_single_test_file_read_only(self):
        f = self.root / "tests_synchronisation.py"
        f.write_text("def test_imap(): assert False")
        p = subprocess.CompletedProcess([], 1, stdout="FAILED x\nAssertionError")
        with patch("adaptive_llm_router.bugsinpy_reproduce.subprocess.run",
                   return_value=p) as proc:
            row = docker_test(
                "adaptive-bugsinpy:py36", self.root,
                ["python", "-m", "pytest", "tqdm/tests/tests_synchronisation.py::test_imap"],
                regression_test_from_fixed=f,
            )
        self.assertEqual(row["verdict"], "test_failure")
        docker_args = proc.call_args.args[0]
        self.assertIn("--network=none", docker_args)
        self.assertIn("--read-only", docker_args)
        self.assertIn("dst=/src/tqdm/tests/tests_synchronisation.py,readonly",
                      " ".join(docker_args))
        with self.assertRaises(ReplayError):
            docker_test("adaptive-bugsinpy:py36", self.root, ["python", "-m", "pytest", "test.py"],
                        regression_test_from_fixed=self.root / "arbitrary_file.py")

    def test_tqdm_backport_fallback_keeps_both_logs(self):
        buggy = self.root / "buggy"
        fixed = self.root / "fixed"
        buggy.mkdir()
        (fixed / "tqdm/tests").mkdir(parents=True)
        test_file = fixed / "tqdm/tests/tests_synchronisation.py"
        test_file.write_text("def test_imap(): assert False\n")
        record = {
            "case_id": "tqdm-6", "project": "tqdm", "docker_image": "adaptive-bugsinpy:py36",
            "test_commands": [["python", "-m", "pytest",
                               "tqdm/tests/tests_synchronisation.py::test_imap"]],
        }
        results = iter([
            {"verdict": "test_not_collected", "output": "ERROR: not found", "exit_code": 4},
            {"verdict": "test_failure", "output": "AssertionError", "exit_code": 1},
            {"verdict": "pass", "output": "1 passed", "exit_code": 0},
        ])
        overrides = []
        def mock_docker(*args, **kwargs):
            overrides.append(kwargs.get("regression_test_from_fixed"))
            return next(results)
        with patch("adaptive_llm_router.bugsinpy_reproduce.subprocess.run"), \
             patch("adaptive_llm_router.bugsinpy_reproduce.checkout_versions",
                   return_value={"buggy": buggy, "fixed": fixed}), \
             patch("adaptive_llm_router.bugsinpy_reproduce.docker_test",
                   side_effect=mock_docker):
            out = run_one(record, self.root, self.root / "outputs")
        self.assertEqual(out["status"], REPRODUCED)
        self.assertEqual(overrides, [None, test_file, None])
        self.assertTrue(out["regression_test_backport"]["no_implementation_patch_copied"])
        self.assertEqual(out["tests"]["buggy"][0]["test_origin"],
                         "fixed_commit_regression_test_only")
        self.assertTrue((self.root / "outputs/tqdm-6_buggy_1_missing_test.log").exists())
        self.assertTrue((self.root / "outputs/tqdm-6_buggy_1.log").exists())
        self.assertTrue((self.root / "outputs/tqdm-6_fixed_1.log").exists())
        self.assertIsNone(out["llm_verified_success"])


if __name__ == "__main__":
    unittest.main()
