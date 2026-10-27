"""CPU-only tests of four remaining pinned Tornado verifier-only regressions.

Actual historical repositories and Docker containers are never executed here.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.bugsinpy_reproduce import (
    REPRODUCED, REGRESSION_TEST_FILES, REVISED_REGRESSION_TEST_CASES,
    TORNADO_REMAINING, ReplayError, docker_test, main, run_one,
)


class RemainingTornadoBackportTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_four_cases_frozen_and_only_tornado7_uses_revised_test(self):
        self.assertEqual(TORNADO_REMAINING, (
            "tornado-5", "tornado-7", "tornado-11", "tornado-14",
        ))
        self.assertEqual(REVISED_REGRESSION_TEST_CASES, {"tornado-7"})
        for case in TORNADO_REMAINING:
            self.assertIn(case, REGRESSION_TEST_FILES)
            self.assertTrue(REGRESSION_TEST_FILES[case].startswith("tornado/test/"))
        self.assertEqual(REGRESSION_TEST_FILES["tornado-11"],
                         "tornado/test/httpserver_test.py")

    def exercise_replay(self, case_id, original_verdict):
        buggy = self.root / "buggy"
        fixed = self.root / "fixed"
        buggy.mkdir(exist_ok=True)
        fixed.mkdir(exist_ok=True)
        rel = REGRESSION_TEST_FILES[case_id]
        testfile = fixed / rel
        testfile.parent.mkdir(parents=True, exist_ok=True)
        testfile.write_text("def sentinel_no_fix_implementation(): pass\n")
        record = {
            "case_id": case_id,
            "project": "tornado",
            "docker_image": "adaptive-bugsinpy:py37",
            "test_commands": [
                ["python", "-m", "unittest", "-q", "tornado.test.sample.Class.test_method"]
            ],
        }
        outcomes = iter([
            {"verdict": original_verdict, "output": "historical original", "exit_code": 1},
            {"verdict": "test_failure", "output": "AssertionError", "exit_code": 1},
            {"verdict": "pass", "output": "Ran 1 test\nOK", "exit_code": 0},
        ])
        bindings = []
        def fake_test(*args, **kwargs):
            bindings.append(kwargs.get("regression_test_from_fixed"))
            return next(outcomes)
        outfolder = self.root / (case_id + "-output")
        with patch("adaptive_llm_router.bugsinpy_reproduce.subprocess.run"), \
             patch("adaptive_llm_router.bugsinpy_reproduce.checkout_versions",
                   return_value={"buggy": buggy, "fixed": fixed}), \
             patch("adaptive_llm_router.bugsinpy_reproduce.docker_test", side_effect=fake_test):
            outcome = run_one(record, self.root, outfolder)
        self.assertEqual(outcome["status"], REPRODUCED)
        self.assertEqual(bindings, [None, testfile, None])
        self.assertTrue(outcome["verified_historical_reproduction"])
        self.assertTrue(outcome["regression_test_backport"]["no_implementation_patch_copied"])
        self.assertEqual(outcome["regression_test_backport"]["fixed_test_file"], rel)
        self.assertEqual(outcome["tests"]["buggy"][0]["test_origin"],
                         "fixed_commit_regression_test_only")
        self.assertIsNone(outcome["llm_verified_success"])
        self.assertTrue((outfolder / f"{case_id}_buggy_1.log").exists())
        self.assertTrue((outfolder / f"{case_id}_fixed_1.log").exists())
        self.assertEqual(json.loads((outfolder / (case_id + ".json")).read_text())["status"],
                         REPRODUCED)
        return outfolder, outcome

    def test_missing_fixed_regression_tests_replay_only_verifier_test(self):
        for case_id in ("tornado-5", "tornado-11", "tornado-14"):
            with self.subTest(case=case_id):
                folder, outcome = self.exercise_replay(case_id, "test_not_collected")
                self.assertTrue((folder / f"{case_id}_buggy_1_missing_test.log").exists())
                self.assertEqual(
                    outcome["regression_test_backport"]["attempts"][0]["test_overlay_reason"],
                    "missing_regression_test_in_buggy_commit",
                )

    def test_modified_tornado7_test_overlaid_even_if_old_test_passes(self):
        folder, outcome = self.exercise_replay("tornado-7", "pass")
        self.assertTrue((folder / "tornado-7_buggy_1_revised_test_original.log").exists())
        backport = outcome["regression_test_backport"]
        self.assertIsNone(backport["missing_test_log"])
        self.assertEqual(backport["attempts"][0]["original_verdict"], "pass")
        self.assertEqual(backport["attempts"][0]["test_overlay_reason"],
                         "fixed_commit_revised_test")

    def test_docker_single_test_only_read_only_binding(self):
        for rel in ("tornado/test/ioloop_test.py", "tornado/test/httpserver_test.py"):
            with self.subTest(path=rel):
                path = self.root / "fixed" / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# verifier-only test\n")
                completed = subprocess.CompletedProcess(
                    args=[], returncode=1, stdout="FAIL: test_example\nFAILED (failures=1)",
                    stderr="")
                with patch("adaptive_llm_router.bugsinpy_reproduce.subprocess.run",
                           return_value=completed) as proc:
                    result = docker_test(
                        "adaptive-bugsinpy:py37", self.root,
                        ["python", "-m", "unittest", "-q", "tests.Case.test"],
                        regression_test_from_fixed=path,
                    )
                self.assertEqual(result["verdict"], "test_failure")
                cmd = proc.call_args.args[0]
                for flag in ("--network=none", "--read-only", "--cap-drop=ALL",
                             "--security-opt=no-new-privileges"):
                    self.assertIn(flag, cmd)
                self.assertIn(f"dst=/src/{rel},readonly", " ".join(cmd))
        with self.assertRaises(ReplayError):
            external_path = self.root / "fake" / "ioloop_test.py"
            external_path.parent.mkdir()
            external_path.write_text("do_not_run")
            docker_test(
                "adaptive-bugsinpy:py37", self.root, ["python", "-m", "unittest", "-q", "tests.X.test"],
                regression_test_from_fixed=external_path,
            )

    def test_tornado_remaining_cli_is_only_four_and_safe_dry_run(self):
        output = self.root / "out-cli"
        argv = ["reproduce", "--dataset-root", str(self.root),
                "--workspace", str(self.root / "workspace"),
                "--output-root", str(output), "--cases", "tornado-remaining"]
        with patch.object(sys, "argv", argv), \
             patch("adaptive_llm_router.bugsinpy_reproduce.prepare_metadata",
                   side_effect=lambda dataset, case: {"case_id": case, "status": "not_executed"}) as prepare, \
             patch("adaptive_llm_router.bugsinpy_reproduce.run_one",
                   side_effect=AssertionError("dry run must not execute external tests")):
            main()
        self.assertEqual(prepare.call_count, 4)
        data = json.loads((output / "reproduction_summary.json").read_text())
        self.assertFalse(data["executed"])
        self.assertEqual([x["id"] for x in data["cases"]], list(TORNADO_REMAINING))
        self.assertEqual(data["verified_reproductions"], 0)


if __name__ == "__main__":
    unittest.main()
