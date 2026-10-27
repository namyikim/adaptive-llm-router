"""No Docker/API calls: patch validation, verifier execution gates, honest comparisons."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.bugsinpy_patch_verifier import (
    CandidatePatchError, read_candidate_patch, verify_patch,
)
from adaptive_llm_router.bugsinpy_patch_compare import compare_patch_trials
from adaptive_llm_router.bugsinpy_blind_tasks import prepare_tasks

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "benchmarks/data/bugsinpy_six_historical_reproductions.json"

DIFF = (
    "diff --git a/tornado/ioloop.py b/tornado/ioloop.py\n"
    "index 1111111..2222222 100644\n"
    "--- a/tornado/ioloop.py\n"
    "+++ b/tornado/ioloop.py\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+new\n"
)


class CandidatePatchVerificationTests(unittest.TestCase):
    def setUp(self):
        ctx = tempfile.TemporaryDirectory()
        self.addCleanup(ctx.cleanup)
        self.root = Path(ctx.name)
        self.patchfile = self.root / "candidate.patch"
        self.patchfile.write_text(DIFF, encoding="utf-8")

    def test_valid_production_only_diff(self):
        blob, files = read_candidate_patch(self.patchfile, "tornado-7")
        self.assertEqual(files, ["tornado/ioloop.py"])
        self.assertIn(b"diff --git", blob)
        with self.assertRaises(CandidatePatchError):
            read_candidate_patch(self.patchfile, "tqdm-6")

    def test_rejects_tests_symlinks_binary_modes_paths_and_huge_patches(self):
        unsafe = [
            DIFF.replace("tornado/ioloop.py", "tornado/test/ioloop_test.py"),
            DIFF.replace("tornado/ioloop.py", "tornado/../ioloop.py"),
            DIFF.replace("tornado/ioloop.py", "tornado/../../other.py"),
            DIFF.replace("tornado/ioloop.py", "tornado/ioloop.sh"),
            DIFF.replace("tornado/ioloop.py", "tornado/setup.py"),
            DIFF.replace("index 1111111..2222222 100644",
                         "new file mode 100644"),
            DIFF.replace("index 1111111..2222222 100644",
                         "rename from tornado/a.py"),
            DIFF.replace("+++ b/tornado/ioloop.py", "+++ /dev/null"),
            "diff --git a/tornado/ioloop.py b/tornado/other.py\n"+DIFF,
            DIFF + "GIT binary patch\n",
            DIFF.replace("@@ -1 +1 @@", "chmod +x"),
        ]
        for text in unsafe:
            with self.subTest(text=text[:75]):
                self.patchfile.write_text(text, encoding="utf-8")
                with self.assertRaises(CandidatePatchError):
                    read_candidate_patch(self.patchfile, "tornado-7")
        self.patchfile.write_bytes(b"\x00")
        with self.assertRaises(CandidatePatchError):
            read_candidate_patch(self.patchfile, "tornado-7")
        self.patchfile.write_text("a" * 32769)
        with self.assertRaises(CandidatePatchError):
            read_candidate_patch(self.patchfile, "tornado-7")
        self.patchfile.unlink()
        (self.root / "original").write_text(DIFF)
        self.patchfile.symlink_to(self.root / "original")
        with self.assertRaises(CandidatePatchError):
            read_candidate_patch(self.patchfile, "tornado-7")

    def test_missing_candidate_is_neither_success_nor_failure(self):
        out = self.root / "results"
        with patch("adaptive_llm_router.bugsinpy_patch_verifier.checkout_versions",
                   side_effect=AssertionError("dry run must not fetch repo")):
            row = verify_patch(dataset_root=self.root, workspace=self.root,
                output_root=out, case_id="tornado-7", tier="l2",
                model_id="external-test-model",
                patch_file=None, execute=False)
        self.assertEqual(row["status"], "awaiting_candidate_patch")
        self.assertIsNone(row["regression_passed"])
        self.assertFalse(row["executed"])
        self.assertFalse(row["llm_called_by_verifier"])
        self.assertFalse(row["full_bugfix_certified"])

    def test_dry_run_patch_validation_no_external_code_execution(self):
        out = self.root / "results"
        with patch("adaptive_llm_router.bugsinpy_patch_verifier.checkout_versions",
                   side_effect=AssertionError("no git")), \
             patch("adaptive_llm_router.bugsinpy_patch_verifier.docker_test",
                   side_effect=AssertionError("no Docker")):
            row = verify_patch(dataset_root=self.root, workspace=self.root,
                output_root=out, case_id="tornado-7", tier="l3",
                model_id="external-test-model", patch_file=self.patchfile,
                execute=False)
        self.assertEqual(row["status"], "not_executed")
        self.assertFalse(row["executed"])
        self.assertIn("patch_sha256", row)
        self.assertIsNone(row["model_cost_usd_observed"])

    def test_invalid_observed_measurements_are_rejected(self):
        for value in (-1, float("nan"), float("inf"), True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    verify_patch(dataset_root=self.root, workspace=self.root,
                        output_root=self.root / "out", case_id="tornado-7", tier="l2",
                        model_id="model", patch_file=None, model_cost_usd=value)

    def test_verified_patch_needs_baseline_failure_fixed_pass_and_candidate_pass(self):
        # Simulate git worktree, but never invoke it or run historical code.
        source = self.root / "work" / "repos" / "tornado"
        buggy = self.root / "buggy"
        fixed = self.root / "fixed"
        source.mkdir(parents=True)
        buggy.mkdir()
        (fixed / "tornado/test").mkdir(parents=True)
        (fixed / "tornado/test/ioloop_test.py").write_text("verifier only")
        calls = []
        def fake_run(argv, **kwargs):
            calls.append(argv)
            if "worktree" in argv and "add" in argv:
                target = Path(argv[argv.index("add") + 2])
                (target / "tornado").mkdir(parents=True)
                (target / "tornado/ioloop.py").write_text("old\n")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        observations = iter([
            "test_failure", "pass", "pass",
        ])
        def fake_test(*args, **kwargs):
            return {"command": args[2], "verdict": next(observations),
                    "exit_code": 1, "duration_seconds": 0.01, "output": "test log"}
        metadata = {
            "project": "tornado", "docker_image": "adaptive-bugsinpy:py37",
            "buggy_commit": "a" * 40, "fixed_commit_for_verifier_only": "b" * 40,
            "test_commands": [["python", "-m", "unittest", "-q", "tests.TestCase.test"]],
        }
        # Source checkout repo exists, but mocked Git never executes code.
        with patch("adaptive_llm_router.bugsinpy_patch_verifier.prepare_metadata",
                   return_value=metadata), \
             patch("adaptive_llm_router.bugsinpy_patch_verifier.checkout_versions",
                   return_value={"buggy": buggy, "fixed": fixed}), \
             patch("adaptive_llm_router.bugsinpy_patch_verifier.subprocess.run",
                   side_effect=fake_run), \
             patch("adaptive_llm_router.bugsinpy_patch_verifier.docker_test",
                   side_effect=fake_test):
            row = verify_patch(dataset_root=self.root, workspace=self.root / "work",
                output_root=self.root / "results", case_id="tornado-7", tier="l2",
                model_id="external-L2", patch_file=self.patchfile,
                execute=True, model_cost_usd=0.01, model_latency_ms=100.0)
        self.assertEqual(row["status"], "regression_passed")
        self.assertTrue(row["regression_passed"])
        self.assertFalse(row["full_bugfix_certified"])
        self.assertEqual(row["baseline_verification_status"],
                         "reproduced_buggy_fail_fixed_pass")
        self.assertEqual(row["candidate_tests"][0]["verdict"], "pass")
        self.assertEqual(row["model_cost_usd_observed"], 0.01)
        self.assertTrue(any("apply" in x for x in calls))
        self.assertTrue(any("worktree" in x and "remove" in x for x in calls))
        self.assertTrue((self.root / "results/logs/tornado-7_l2_candidate_1.log").exists())

    def test_same_frozen_prompts_for_both_tiers_without_fixed_code(self):
        tasks = prepare_tasks(AUDIT)
        self.assertEqual(len(tasks), 6)
        for task in tasks:
            with self.subTest(task=task["case_id"]):
                self.assertEqual(task["tiers_to_compare"], ["l2", "l3"])
                self.assertEqual(task["symptom_provenance"],
                                 "historical_verifier_derived_hint_not_blind_bug_report")
                for forbidden in ("fixed_commit", "verifier_test_file",
                                  "fixed_patch", "solution", "test_code"):
                    self.assertNotIn(forbidden, task)
                self.assertNotIn("https://github.com/namyikim", task["prompt"])


class PatchPairComparisonTests(unittest.TestCase):
    def setUp(self):
        ctx = tempfile.TemporaryDirectory()
        self.addCleanup(ctx.cleanup)
        self.root = Path(ctx.name)

    def write(self, case, tier, passed, cost=None):
        row = {
            "evaluation": "independent_candidate_patch_regression_only",
            "case_id": case, "tier": tier,
            "executed": True, "baseline_verification_status": "reproduced_buggy_fail_fixed_pass",
            "model_id": f"external-{tier}", "patch_sha256": "a" * 64,
            "status": "regression_passed" if passed else "regression_failed",
            "regression_passed": passed, "model_cost_usd_observed": cost,
        }
        (self.root / f"{case}_{tier}.json").write_text(json.dumps(row))

    def test_incomplete_pairs_do_not_become_measured_six_case_success_rate(self):
        self.write("tornado-7", "l2", False, 0.01)
        self.write("tornado-7", "l3", True, 0.07)
        self.write("tornado-5", "l2", True)
        result = compare_patch_trials(self.root)
        self.assertEqual(result["n_complete_pairs"], 1)
        self.assertEqual(result["n_cases_l3_helped_when_l2_failed"], 1)
        self.assertEqual(result["n_incomplete_pairs"], 5)
        self.assertIsNone(result["overall_six_case_success_rates"])
        self.assertIsNone(result["mean_model_cost_usd_observed"])
        self.assertTrue(any(not r["complete_independent_pair"] for r in result["cases"]))

    def test_all_six_independent_verified_pairs_have_real_denominator(self):
        from adaptive_llm_router.bugsinpy_reproduce import ALLOWED_CASES
        for case in ALLOWED_CASES:
            self.write(case, "l2", True, 0.02)
            self.write(case, "l3", True, 0.05)
        result = compare_patch_trials(self.root)
        self.assertTrue(result["all_six_pairs_complete"])
        self.assertEqual(result["overall_six_case_success_rates"],
                         {"l2": 1.0, "l3": 1.0})
        self.assertAlmostEqual(result["mean_model_cost_usd_observed"]["l3"], 0.05)


if __name__ == "__main__":
    unittest.main()
