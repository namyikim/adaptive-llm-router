"""CPU-only contract for historical reproduction evidence, never model accuracy."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "benchmarks/data/bugsinpy_six_historical_reproductions.json"


class VerifiedHistoricalEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(DATA.read_text(encoding="utf-8"))

    def test_cases_and_independent_source_artifacts(self):
        d = self.evidence
        expected = {"tqdm-6", "tornado-5", "tornado-6",
                    "tornado-7", "tornado-11", "tornado-14"}
        self.assertEqual(d["record_type"], "audited_historical_bug_reproduction_only")
        self.assertEqual(d["n_cases"], 6)
        self.assertEqual(d["n_buggy_fail_fixed_pass_from_logs"], 6)
        self.assertEqual(d["n_machine_verified"], 5)
        self.assertEqual({x["id"] for x in d["cases"]}, expected)
        for row in d["cases"]:
            with self.subTest(case=row["id"]):
                self.assertTrue(row["run_url"].endswith("/" + str(row["run_id"])))
                self.assertGreater(row["artifact_id"], 0)
                self.assertTrue(row["buggy_errors"])
                self.assertGreaterEqual(row["n_tests"], 1)
                self.assertIn(row["status"], {
                    "log_verified_buggy_fail_fixed_pass",
                    "log_and_machine_verified_buggy_fail_fixed_pass",
                })
                self.assertTrue(row["verifier_only_fixed_commit_regression_test"])
                self.assertFalse(row["fixed_implementation_provided_to_llm"])
                self.assertFalse(row["llm_repair_attempted"])
                self.assertIsNone(row["llm_verified_success"])

    def test_historical_tqdm_false_negative_is_not_rewritten(self):
        rows = {x["id"]: x for x in self.evidence["cases"]}
        self.assertEqual(rows["tqdm-6"]["original_machine_status"],
                         "environment_or_timeout")
        self.assertEqual(rows["tqdm-6"]["status"],
                         "log_verified_buggy_fail_fixed_pass")
        self.assertEqual(rows["tornado-7"]["run_id"], 40438878278)
        self.assertEqual(
            {rows[k]["run_id"] for k in ("tornado-5","tornado-7","tornado-11","tornado-14")},
            {40438878278},
        )

    def test_critical_fixed_patch_is_not_in_evidence(self):
        d = self.evidence
        prohibited = {"fixed_patch", "patch_content", "solution",
                      "model_input", "prompt", "fixed_source", "fixed_diff"}
        for row in d["cases"]:
            with self.subTest(case=row["id"]):
                self.assertFalse(prohibited.intersection(row))
                self.assertNotIn("correctness_rate", row)
                self.assertNotIn("llm_passed", row)


if __name__ == "__main__":
    unittest.main()
