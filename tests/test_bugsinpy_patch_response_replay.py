"""Offline historical LLM response replay contract tests."""
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.bugsinpy_patch_response_replay import replay_response
from adaptive_llm_router.bugsinpy_reproduce import ReplayError

DIFF = ("diff --git a/tqdm/_tqdm.py b/tqdm/_tqdm.py\n"
        "--- a/tqdm/_tqdm.py\n+++ b/tqdm/_tqdm.py\n"
        "@@ -1 +1 @@\n-old\n+new\n")


class PatchResponseReplayTests(unittest.TestCase):
    def test_replay_archive_without_network_or_docker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            response = root / "l2_provider_response.txt"
            response.write_text("Suggested change:\n" + DIFF)
            patch = root / "l2.diff"
            result = replay_response("tqdm-6", response, patch)
            self.assertEqual(patch.read_bytes(), DIFF.encode())
            self.assertFalse(result["paid_api_called"])
            self.assertIsNone(result["verified_patch_success"])
            self.assertEqual(result["status"], "candidate_extracted_not_tested")
            with self.assertRaises(ReplayError):
                replay_response("tqdm-6", response, patch)

    def test_invalid_text_cannot_be_recovered_by_inventing_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            response = root / "l3_provider_response.txt"
            response.write_text("The code needs a fix, but no unified diff.")
            patch = root / "l3.diff"
            with self.assertRaises(ReplayError):
                replay_response("tqdm-6", response, patch)
            self.assertFalse(patch.exists())


if __name__ == "__main__":
    unittest.main()
