"""No-network regression tests for current Claude models and useful paid preflight."""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from adaptive_llm_router.bugsinpy_llm_patch_generate import call_anthropic


class CurrentClaudeCompatibilityTests(unittest.TestCase):
    def test_sonnet_and_opus_five_five_have_no_unsupported_sampling_fields(self):
        for model in ("claude-sonnet-5-5", "claude-opus-5-5"):
            with self.subTest(model=model):
                captured = []
                def mock_open(request, timeout):
                    payload = json.loads(request.data)
                    captured.append(payload)
                    self.assertEqual(request.full_url, "https://api.anthropic.com/v1/messages")
                    self.assertEqual(timeout, 180)
                    return io.BytesIO(json.dumps({
                        "model": model, "id": "test-id",
                        "stop_reason": "end_turn",
                        "usage": {"input_tokens": 5, "output_tokens": 10},
                        "content": [{"type": "text", "text": "diff --git a/x b/x"}],
                    }).encode("utf-8"))
                with patch("adaptive_llm_router.bugsinpy_llm_patch_generate.urllib.request.urlopen",
                           side_effect=mock_open):
                    result = call_anthropic(
                        "Please fix this bug", model, "dummy-not-real-credential", 4096)
                self.assertEqual(result["model"], model)
                self.assertEqual(len(captured), 1)
                self.assertNotIn("temperature", captured[0])
                self.assertNotIn("top_p", captured[0])
                self.assertNotIn("top_k", captured[0])
                self.assertEqual(captured[0]["max_tokens"], 4096)
                self.assertEqual(len(captured[0]["messages"]), 1)

    def test_workflow_provides_separate_safe_error_messages(self):
        text = (ROOT / ".github/workflows/bugsinpy-llm-eval.yml").read_text("utf-8")
        for snippet in (
            "Missing l2_model", "Missing l3_model", "Same model ID",
            "Missing GitHub secret", "Nothing was billed",
            "Free dry-run mode", "default: false",
            "secrets.ANTHROPIC_API_KEY",
        ):
            self.assertIn(snippet, text)
        self.assertNotIn("Paid mode needs ANTHROPIC_API_KEY secret and distinct explicit model IDs.", text)


if __name__ == "__main__":
    unittest.main()
