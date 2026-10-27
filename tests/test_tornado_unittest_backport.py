"""Regression tests for Tornado-6's fixed-commit-only unittest class."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.bugsinpy_reproduce import (
    REPRODUCED, ReplayError, classify_test_output, classify_reproduction, docker_test,
    run_one,
)

MISSING_CLASS_LOG = """
======================================================================
ERROR: LeakTest (unittest.loader._FailedTest)
----------------------------------------------------------------------
AttributeError: module 'tornado.test.asyncio_test' has no attribute 'LeakTest'

----------------------------------------------------------------------
Ran 1 test in 0.000s

FAILED (errors=1)
"""


class TornadoRegressionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_real_tornado_missing_class_is_not_bug_failure(self):
        self.assertEqual(classify_test_output(1, MISSING_CLASS_LOG),
                         "test_not_collected")
        self.assertEqual(classify_reproduction(
            [{"verdict": "test_not_collected"}], [{"verdict": "pass"}]),
            "environment_or_timeout")
        self.assertEqual(classify_test_output(
            1, "ERROR: LeakTest (unittest.loader._FailedTest)\n"
               "ImportError: No module named 'fake'"), "environment_failure")

    def test_genuine_unittest_assertion_is_recognized(self):
        self.assertEqual(classify_test_output(
            1, "FAIL: test_ioloop_close_leak (tornado.test.asyncio_test.LeakTest)\n"
               "AssertionError: 10 != 0\n\nFAILED (failures=1)"),
            "test_failure")

    def test_overlay_is_single_fixed_commit_test_only(self):
        test = self.root / "tornado/test/asyncio_test.py"
        test.parent.mkdir(parents=True)
        test.write_text("class LeakTest: pass\n")
        expected = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="FAIL: test_ioloop_close_leak (tornado.test.asyncio_test.LeakTest)\nFAILED (failures=1)", stderr="")
        with patch("adaptive_llm_router.bugsinpy_reproduce.subprocess.run",
                   return_value=expected) as proc:
            res = docker_test(
                "adaptive-bugsinpy:py37", self.root,
                ["python", "-m", "unittest", "-q",
                 "tornado.test.asyncio_test.LeakTest.test_ioloop_close_leak"],
                regression_test_from_fixed=test)
        self.assertEqual(res["verdict"], "test_failure")
        args = proc.call_args.args[0]
        self.assertIn("--network=none", args)
        self.assertIn("--read-only", args)
        self.assertIn("dst=/src/tornado/test/asyncio_test.py,readonly", " ".join(args))
        with self.assertRaises(ReplayError):
            docker_test("adaptive-bugsinpy:py37", self.root,
                        ["python", "-m", "unittest", "-q", "tornado.test.x.Test.y"],
                        regression_test_from_fixed=self.root / "tornado/fake.py")

    def test_each_absent_tornado_test_retries_with_test_only(self):
        buggy = self.root / "buggy"
        fixed = self.root / "fixed"
        buggy.mkdir()
        file = fixed / "tornado/test/asyncio_test.py"
        file.parent.mkdir(parents=True)
        file.write_text("class LeakTest: pass\n", encoding="utf-8")
        tests = [
            ["python", "-m", "unittest", "-q",
             "tornado.test.asyncio_test.LeakTest.test_ioloop_close_leak"],
            ["python", "-m", "unittest", "-q",
             "tornado.test.asyncio_test.LeakTest.test_asyncio_close_leak"],
        ]
        record = {"case_id": "tornado-6", "project": "tornado",
                  "docker_image": "adaptive-bugsinpy:py37", "test_commands": tests}
        sequence = iter([
            {"verdict": "test_not_collected", "output": MISSING_CLASS_LOG, "exit_code": 1},
            {"verdict": "test_failure", "output": "FAIL: test_ioloop_close_leak\n", "exit_code": 1},
            {"verdict": "test_not_collected", "output": MISSING_CLASS_LOG, "exit_code": 1},
            {"verdict": "test_failure", "output": "FAIL: test_asyncio_close_leak\n", "exit_code": 1},
            {"verdict": "pass", "output": "Ran 1 test\nOK", "exit_code": 0},
            {"verdict": "pass", "output": "Ran 1 test\nOK", "exit_code": 0},
        ])
        overlays = []
        def run_fake(*args, **kwargs):
            overlays.append(kwargs.get("regression_test_from_fixed"))
            return next(sequence)
        with patch("adaptive_llm_router.bugsinpy_reproduce.subprocess.run"), \
             patch("adaptive_llm_router.bugsinpy_reproduce.checkout_versions",
                   return_value={"buggy": buggy, "fixed": fixed}), \
             patch("adaptive_llm_router.bugsinpy_reproduce.docker_test", side_effect=run_fake):
            out = run_one(record, self.root, self.root / "outputs")
        self.assertEqual(out["status"], REPRODUCED)
        self.assertEqual(overlays, [None, file, None, file, None, None])
        self.assertEqual(len(out["regression_test_backport"]["attempts"]), 2)
        self.assertTrue(out["regression_test_backport"]["no_implementation_patch_copied"])
        self.assertEqual(out["regression_test_backport"]["fixed_test_file"],
                         "tornado/test/asyncio_test.py")
        for i in (1, 2):
            self.assertTrue((self.root / f"outputs/tornado-6_buggy_{i}_missing_test.log").is_file())
            self.assertTrue((self.root / f"outputs/tornado-6_buggy_{i}.log").is_file())
            self.assertTrue((self.root / f"outputs/tornado-6_fixed_{i}.log").is_file())
            self.assertEqual(out["tests"]["buggy"][i-1]["test_origin"],
                             "fixed_commit_regression_test_only")
        self.assertIsNone(out["llm_verified_success"])


if __name__ == "__main__":
    unittest.main()
