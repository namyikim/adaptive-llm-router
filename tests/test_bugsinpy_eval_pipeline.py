"""Unit tests for single-case L2/L3 integrated evaluator: no real API or Docker."""
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.bugsinpy_eval_pipeline import load_reviewed_symptom, run_pipeline
from adaptive_llm_router.bugsinpy_reproduce import EXPECTED_COMMITS, ReplayError

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "benchmarks/data/bugsinpy_six_historical_reproductions.json"
WORKFLOW = ROOT / ".github/workflows/bugsinpy-llm-eval.yml"
DIFF = ("diff --git a/tqdm/_tqdm.py b/tqdm/_tqdm.py\n"
        "--- a/tqdm/_tqdm.py\n+++ b/tqdm/_tqdm.py\n"
        "@@ -1 +1 @@\n-old\n+new\n")
DIGEST = hashlib.sha256(DIFF.encode()).hexdigest()

class E2EConfigTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.kw = dict(case_id="tqdm-6", dataset_root=self.root / "data",
                       workspace=self.root / "work", evidence_path=EVIDENCE,
                       output_root=self.root / "results")
        self.metadata = {"case_id": "tqdm-6",
                         "buggy_commit": EXPECTED_COMMITS["tqdm-6"][0],
                         "docker_image": "adaptive-bugsinpy:py36", "test_commands": []}
        self.prompt = {"prompt": "Original buggy source only", "input_sha256": "a"*64}

    def mocks(self):
        return (patch("adaptive_llm_router.bugsinpy_eval_pipeline.prepare_metadata",
                      return_value=self.metadata),
                patch("adaptive_llm_router.bugsinpy_eval_pipeline.checkout_versions",
                      return_value={"buggy": self.root / "buggy", "fixed": self.root / "fixed"}),
                patch("adaptive_llm_router.bugsinpy_eval_pipeline.prepare",
                      return_value=self.prompt))

    def test_evidence_explicitly_oracle_assisted(self):
        data = load_reviewed_symptom(EVIDENCE, "tqdm-6")
        self.assertIn("AttributeError", data["observation"])
        self.assertIn("oracle", data["symptom_provenance"])
        self.assertEqual(data["source_run_id"], 40428395903)
        with self.assertRaises(ReplayError):
            load_reviewed_symptom(EVIDENCE, "tornado-999")

    def test_dry_run_never_calls_provider_or_docker(self):
        a,b,c = self.mocks()
        with a,b,c, patch("adaptive_llm_router.bugsinpy_eval_pipeline.call_anthropic",
                          side_effect=AssertionError("no API")), patch(
            "adaptive_llm_router.bugsinpy_eval_pipeline.verify_patch",
            side_effect=AssertionError("no Docker")):
            out = run_pipeline(**self.kw)
        self.assertEqual(out["status"], "dry_run_no_api_no_patch_tests")
        self.assertEqual(out["comparison"]["status"], "not_measured")
        self.assertTrue((self.root / "results/e2e_summary.json").exists())
        self.assertIsNone(out["results"]["l2"]["verified_patch_success"])

    def test_explicit_paid_and_docker_gate(self):
        with self.assertRaises(ValueError):
            run_pipeline(**self.kw, execute_patch_tests=True)
        with self.assertRaises(ValueError):
            run_pipeline(**self.kw, allow_paid_api=True)
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "placeholder"}):
            with self.assertRaises(ValueError):
                run_pipeline(**self.kw, allow_paid_api=True,
                             l2_model="same", l3_model="same")

    def test_same_patch_two_distinct_verification_workspaces(self):
        a,b,c = self.mocks()
        calls, paths = [], []
        def paid(prompt, model, key, max_tokens):
            calls.append(model)
            return {"model": model, "answer": DIFF, "id": model,
                    "usage": {"input_tokens": 25}, "elapsed_ms": 100}
        def verify(*, dataset_root, patch_file, workspace, output_root,
                   case_id, tier, model_id, execute, model_latency_ms):
            self.assertTrue(execute)
            self.assertEqual(hashlib.sha256(patch_file.read_bytes()).hexdigest(), DIGEST)
            paths.append(str(workspace))
            return {"patch_sha256": DIGEST,
                    "regression_passed": len(paths)==1,
                    "status": "regression_passed" if len(paths)==1 else "regression_failed"}
        with a,b,c, patch.dict(os.environ, {"ANTHROPIC_API_KEY": "placeholder"}), patch(
            "adaptive_llm_router.bugsinpy_eval_pipeline.call_anthropic",
            side_effect=paid), patch(
            "adaptive_llm_router.bugsinpy_eval_pipeline.verify_patch", side_effect=verify):
            out = run_pipeline(**self.kw, allow_paid_api=True,
                               execute_patch_tests=True,
                               l2_model="model-A", l3_model="model-B")
        self.assertEqual(calls, ["model-A", "model-B"])
        self.assertEqual(len(set(paths)), 2)
        self.assertTrue(out["results"]["l2"]["verified_patch_success"])
        self.assertFalse(out["results"]["l3"]["verified_patch_success"])
        self.assertEqual(out["comparison"]["status"], "both_independently_verified_one_case")
        self.assertIsNone(out["results"]["l2"]["usd_cost"])
        with self.assertRaises(ReplayError):
            run_pipeline(**self.kw)

    def test_unusable_paid_response_is_preserved_without_falsely_claiming_success(self):
        a,b,c = self.mocks()
        calls = []
        def paid(prompt, model, key, max_tokens):
            calls.append(model)
            return {"model": model, "answer": "I recommend editing the constructor.",
                    "id": "paid-but-invalid", "usage": {"input_tokens": 4760,
                    "output_tokens": 1086}, "elapsed_ms": 8000}
        with a,b,c, patch.dict(os.environ, {"ANTHROPIC_API_KEY": "placeholder"}), patch(
            "adaptive_llm_router.bugsinpy_eval_pipeline.call_anthropic", side_effect=paid), patch(
            "adaptive_llm_router.bugsinpy_eval_pipeline.verify_patch",
            side_effect=AssertionError("Invalid diff must not execute Docker")):
            out = run_pipeline(**self.kw, allow_paid_api=True,
                               execute_patch_tests=True,
                               l2_model="model-A", l3_model="model-B")
        self.assertEqual(calls, ["model-A", "model-B"])
        self.assertEqual(out["comparison"]["status"], "insufficient_or_unverified_outcomes")
        for tier in ("l2", "l3"):
            result = out["results"][tier]
            self.assertEqual(result["generation_status"], "provider_responded")
            self.assertEqual(result["status"], "invalid_candidate_diff")
            self.assertEqual(result["failure_stage"], "patch_validation")
            self.assertEqual(result["error_type"], "ReplayError")
            self.assertIsNone(result["verified_patch_success"])
            self.assertEqual(result["usage"]["input_tokens"], 4760)
            self.assertEqual((self.root / "results" / result["response_file"]).read_text(),
                             "I recommend editing the constructor.")
            self.assertFalse((self.root / "results" / (tier + ".diff")).exists())

    def test_generation_only_is_not_measured_success(self):
        a,b,c = self.mocks()
        def paid(prompt, model, key, max_tokens):
            return {"model": model, "answer": DIFF, "id": model,
                    "usage": {}, "elapsed_ms": 100}
        with a,b,c, patch.dict(os.environ, {"ANTHROPIC_API_KEY": "placeholder"}), patch(
            "adaptive_llm_router.bugsinpy_eval_pipeline.call_anthropic",
            side_effect=paid), patch(
            "adaptive_llm_router.bugsinpy_eval_pipeline.verify_patch",
            side_effect=AssertionError("no Docker")):
            out = run_pipeline(**self.kw, allow_paid_api=True,
                               l2_model="model-A", l3_model="model-B")
        self.assertIsNone(out["results"]["l2"]["verified_patch_success"])
        self.assertEqual(out["comparison"]["status"], "insufficient_or_unverified_outcomes")

    def test_workflow_no_paid_default(self):
        yaml = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(yaml.count("default: false"), 2)
        self.assertIn("secrets.ANTHROPIC_API_KEY", yaml)
        self.assertIn("--allow-paid-api", yaml)
        self.assertIn("--execute-patch-tests", yaml)
        self.assertIn("if: " + chr(36) + "{{ !inputs.allow_paid_api }}", yaml)
        self.assertIn("if: " + chr(36) + "{{ inputs.allow_paid_api && inputs.execute_patch_tests }}", yaml)
        self.assertNotIn("XX ", yaml)
        self.assertNotIn("YY", yaml)

if __name__ == "__main__":
    unittest.main()
