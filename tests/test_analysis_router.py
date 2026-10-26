import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from adaptive_llm_router.analysis_router import (
    _call_backend, _normalize_openai, DecisionBackendError, load_models,
    prepare_state, routing_questions, select_analysis_model,
)


PROBS = {"l1": 0.12, "l2": 0.80, "l3": 0.08}


class AnalysisRouterTests(unittest.TestCase):
    def test_input_sanitization(self):
        text = (
            "Authorization: Bearer secretverysecretverysecret\n"
            "password=abc123\napi_key: supersecret\n"
            "ghp_12345678901234567890\n"
            "sk-abcdefghijklmnopqrstuvwxyz\n"
            "Traceback: race condition"
        )
        state = prepare_state("log", text)
        for secret in ("secretverysecret", "abc123", "supersecret", "ghp_1234", "sk-abcdef"):
            self.assertNotIn(secret, state)
        self.assertIn("Traceback: race condition", state)
        self.assertIn("[REDACTED", state)

    def test_limits_and_validation(self):
        state = prepare_state("log", "ERROR X" * 4000, max_chars=200)
        self.assertIn("[TRUNCATED", state)
        with self.assertRaises(ValueError):
            prepare_state("other", "hello")
        with self.assertRaises(ValueError):
            prepare_state("code", "")
        self.assertEqual(set(routing_questions("code")["start_tier"]["criteria"]), set(PROBS))

    def test_config(self):
        config = load_models()
        self.assertIn("claude", config["l3"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "models.json"
            path.write_text(json.dumps({"tiers": {"l1": {"model_id": "x"}}}))
            with self.assertRaises(ValueError):
                load_models(path)

    @patch("adaptive_llm_router.analysis_router._post")
    def test_local_kev_model_selection(self, post):
        post.return_value = {
            "model": "kev-latest",
            "answers": {"start_tier": {"type": "choice", "probabilities": PROBS}},
            "latency_ms": 15.0
        }
        result = select_analysis_model("code", "simple script bug", backend="kev")
        self.assertEqual(result.route.tier, "l2")
        self.assertEqual(result.model_id, load_models()["l2"])
        self.assertEqual(result.status, "proposed")
        self.assertIsNone(result.as_dict()["verified_success"])
        payload = post.call_args.args[1]
        self.assertEqual(payload["model"], "kev-latest")

    @patch("adaptive_llm_router.analysis_router._post")
    def test_jev_contract(self, post):
        post.return_value = {"answers": {"start_tier": {"type": "choice", "probabilities": PROBS}}}
        with patch.dict("os.environ", {"TYPESAFE_API_KEY": "placeholder-test-only"}):
            result = select_analysis_model("log", "CUDA OOM", backend="jev", allow_remote=True)
        self.assertEqual(result.route.tier, "l2")
        self.assertEqual(post.call_args.args[1]["model"], "jev-latest")
        self.assertIn("jev", result.backend)

    @patch("adaptive_llm_router.analysis_router._post")
    def test_openai_real_response_shape(self, post):
        post.return_value = {
            "answers": [{
                "name": "start_tier", "type": "choice", "choice": "l2",
                "probabilities": [
                    {"value": "l1", "probability": 0.12},
                    {"value": "l2", "probability": 0.80},
                    {"value": "l3", "probability": 0.08},
                ], "confidence": 0.74
            }]
        }
        with patch.dict("os.environ", {"OPENAI_API_KEY": "placeholder-test-only"}):
            result = select_analysis_model("log", "Error", backend="openai", allow_remote=True)
        self.assertEqual(result.route.tier, "l2")
        # OpenAI confidence is NOT the same thing as max option probability.
        self.assertEqual(result.route.p_max, 0.8)
        payload = post.call_args.args[1]
        self.assertEqual(payload["model"], "gpt-6-luna")
        self.assertEqual(payload["questions"][0]["choices"][0]["value"], "l1")

    def test_remote_opt_in_is_mandatory(self):
        with self.assertRaises(PermissionError):
            select_analysis_model("code", "hi", backend="openai")
        with self.assertRaises(PermissionError):
            select_analysis_model("code", "hi", backend="jev")

    @patch("adaptive_llm_router.analysis_router._post")
    def test_uncertainty_escalates_to_l3(self, post):
        post.return_value = {"answers": {"start_tier": {"type": "choice",
                             "probabilities": {"l1": .40, "l2": .35, "l3": .25}}}}
        result = select_analysis_model("log", "deadlock", min_probability=.65)
        self.assertEqual(result.route.proposed_tier, "l1")
        self.assertEqual(result.route.tier, "l3")
        self.assertTrue(result.route.uncertain)

    @patch("adaptive_llm_router.analysis_router._post")
    def test_backend_failures_conservative_and_visible(self, post):
        post.side_effect = DecisionBackendError("failure")
        result = select_analysis_model("code", "bug")
        self.assertEqual(result.route.tier, "l3")
        self.assertEqual(result.status, "backend_unavailable")
        with self.assertRaises(DecisionBackendError):
            select_analysis_model("code", "bug", fallback_on_error=False)

    def test_refusal_or_bad_openai_response_is_not_accepted(self):
        with self.assertRaises(DecisionBackendError):
            _normalize_openai({"answers": [{"name": "start_tier", "type": "refusal"}]})
        with self.assertRaises(DecisionBackendError):
            _normalize_openai({"answers": []})


if __name__ == "__main__":
    unittest.main()
