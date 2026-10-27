"""The shipped workflow must never schedule or trigger provider calls."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ArchivedReplayWorkflowTests(unittest.TestCase):
    def test_manual_only_default_off_without_provider_credentials(self):
        text = (ROOT / '.github/workflows/bugsinpy-saved-replay.yml').read_text()
        self.assertIn('workflow_dispatch:', text)
        self.assertIn('default: false', text)
        self.assertIn('persist-credentials: false', text)
        self.assertIn('if: ${{ inputs.execute }}', text)
        self.assertNotIn('  push:', text)
        self.assertNotIn('  schedule:', text)
        self.assertNotIn('secrets.', text)
        self.assertNotIn('ANTHROPIC_API_KEY', text)
        self.assertNotIn('--allow-paid-api', text)
        self.assertIn('run_40468990139_responses.json', text)
        source = (ROOT / 'src/adaptive_llm_router/bugsinpy_saved_pair_replay.py').read_text()
        self.assertNotIn('call_anthropic', source)
        self.assertNotIn('urlopen', source)

if __name__ == '__main__':
    unittest.main()
