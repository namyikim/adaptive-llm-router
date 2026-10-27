"""No-network CPU tests of opt-in L2/L3 patch generation. No paid calls."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.bugsinpy_repair_trial import (
    SYSTEM, evidence, models, prompt_for, request_candidate, trial,
    ANCHORS,
)

VALID_DIFF = (
    "diff --git a/tornado/ioloop.py b/tornado/ioloop.py\n"
    "--- a/tornado/ioloop.py\n"
    "+++ b/tornado/ioloop.py\n"
    "@@ -1 +1 @@\n"
    "-badline\n"
    "+goodline\n"
)

class MockResponseProvider:
    def __init__(self, supplied_models, *, diff=VALID_DIFF):
        self.models = list(supplied_models)
        self.calls = []
        self.diff = diff

    def open(self, path, request):
        self.calls.append((path, request))
        return io.BytesIO(json.dumps({
            "content": [{"type": "text", "text": self.diff}],
            "model": self.models.pop(0),
            "usage": {"input_tokens": 122, "output_tokens": 35},
            "stop_reason": "end_turn",
        }).encode())

class PairedRepairTrialTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_dry_run_has_zero_paid_api_calls_no_git_and_no_verification(self):
        mock = MockResponseProvider(["unused"])
        with patch("adaptive_llm_router.bugsinpy_repair_trial.checkout_versions",
                   side_effect=AssertionError("must not checkout public source")), \
             patch("adaptive_llm_router.bugsinpy_repair_trial.prepare_metadata",
                   side_effect=AssertionError("must not clone metadata")), \
             patch("adaptive_llm_router.bugsinpy_repair_trial.verify_patch",
                   side_effect=AssertionError("must not execute Docker")):
            result = trial("tornado-5", workspace=self.root/"workspace",
                           output_root=self.root/"dry", provider=mock)
        self.assertEqual(result["status"], "plan_only")
        self.assertEqual(result["tiers"], {})
        self.assertEqual(len(mock.calls), 0)
        self.assertIsNone(result["actual_cost_usd"])
        self.assertFalse(result["fixed_patch_or_verifier_test_in_prompt"])

    def test_real_audited_cases_and_distinct_configured_models(self):
        ids = models()
        self.assertNotEqual(ids["l2"], ids["l3"])
        for case in ANCHORS:
            with self.subTest(case=case):
                record = evidence(case)
                self.assertEqual(record["id"], case)
                self.assertFalse(record["llm_repair_attempted"])
                self.assertTrue(record["verifier_only_fixed_commit_regression_test"])

    def test_prompt_uses_buggy_source_and_error_only(self):
        source = self.root/"tornado/ioloop.py"
        source.parent.mkdir(parents=True)
        source.write_text("# public buggy file\n" + "def _update_next(" +
                          "self):\n    return self._timeout\n")
        record = evidence("tornado-5")
        prompt = prompt_for("tornado-5", self.root, record)
        self.assertIn("def _update_next(", prompt)
        self.assertIn("only", prompt.lower())
        self.assertIn(record["buggy_errors"][0], prompt)
        self.assertNotIn("fixed_commit_id", prompt)
        self.assertNotIn("fixed_commit_regression_test", prompt)
        self.assertNotIn("test_clock_backwards", prompt)
        self.assertNotIn("test_clock_backwards", SYSTEM)

    def test_pair_generation_records_attribution_tokens_and_verification(self):
        checked = self.root/"buggy"
        source = checked/"tornado/ioloop.py"
        source.parent.mkdir(parents=True)
        source.write_text("def _update_next(self):\n    badline\n")
        requested = models()
        provider = MockResponseProvider([requested["l2"], requested["l3"]])
        calls = []
        def mock_verify(rec, **kwargs):
            calls.append((rec["case_id"], kwargs))
            return {"status":"patch_passed", "verified_patch_success": True}
        with patch("adaptive_llm_router.bugsinpy_repair_trial.prepare_metadata",
                   return_value={"case_id":"tornado-5","buggy_commit":"a"*40}), \
             patch("adaptive_llm_router.bugsinpy_repair_trial.checkout_versions",
                   return_value={"buggy":checked,"fixed":self.root/"not-read"}), \
             patch("adaptive_llm_router.bugsinpy_repair_trial.subprocess.check_output",
                   return_value="a"*40), \
             patch("adaptive_llm_router.bugsinpy_repair_trial.verify_patch",
                   side_effect=mock_verify):
            output = trial("tornado-5", workspace=self.root/"work",
                           output_root=self.root/"paired",
                           dataset_root=self.root/"metadata", allow_paid=True,
                           execute_verifier=True, provider=provider)
        self.assertEqual(output["status"], "finished")
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(len(calls), 2)
        self.assertEqual([c[1]["execute"] for c in calls], [True, True])
        for tier in ("l2","l3"):
            rec = output["tiers"][tier]
            self.assertEqual(rec["input_tokens"], 122)
            self.assertEqual(rec["output_tokens"], 35)
            self.assertTrue(rec["model_identity_matches"])
            self.assertTrue(rec["verified_patch_success"])
            self.assertEqual((self.root/"paired"/(tier+"_candidate.diff")).read_text(),
                             VALID_DIFF)
        self.assertIsNone(output["actual_cost_usd"])
        self.assertFalse((self.root/"paired"/"prompt.txt").exists())

    def test_model_identity_mismatch_never_verifies_patch(self):
        checked = self.root/"buggy"
        path = checked/"tornado/ioloop.py"
        path.parent.mkdir(parents=True)
        path.write_text("def _update_next(self):\n    badline\n")
        desired = models()
        provider = MockResponseProvider(["different-model",desired["l3"]])
        with patch("adaptive_llm_router.bugsinpy_repair_trial.prepare_metadata",
                   return_value={"case_id":"tornado-5","buggy_commit":"b"*40}), \
             patch("adaptive_llm_router.bugsinpy_repair_trial.checkout_versions",
                   return_value={"buggy":checked}), \
             patch("adaptive_llm_router.bugsinpy_repair_trial.subprocess.check_output",
                   return_value="b"*40), \
             patch("adaptive_llm_router.bugsinpy_repair_trial.verify_patch",
                   return_value={"status":"patch_failed","verified_patch_success":False}) as verifier:
            result = trial("tornado-5", workspace=self.root/"work",
                           output_root=self.root/"mismatch",
                           dataset_root=self.root/"meta", allow_paid=True,
                           execute_verifier=True, provider=provider)
        self.assertEqual(result["tiers"]["l2"]["status"], "model_identity_mismatch")
        self.assertIsNone(result["tiers"]["l2"]["verified_patch_success"])
        self.assertFalse((self.root/"mismatch/l2_candidate.diff").exists())
        self.assertEqual(verifier.call_count, 1)
        self.assertFalse(result["tiers"]["l3"]["verified_patch_success"])

    def test_verifier_cannot_run_without_explicit_paid_opt_in(self):
        with self.assertRaises(ValueError):
            trial("tornado-5", workspace=self.root/"work",
                  output_root=self.root/"nope", execute_verifier=True)

if __name__ == "__main__":
    unittest.main()
