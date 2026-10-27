"""Configuration contract: readiness cannot start paid model generation."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TornadoReadinessWorkflowTests(unittest.TestCase):
    def test_manual_no_provider_workflow(self):
        text = (ROOT / '.github/workflows/bugsinpy-tornado-readiness.yml').read_text()
        for wanted in ('workflow_dispatch:', 'default: false',
                       'persist-credentials: false', '--case-id tornado-6',
                       'if: ${{ inputs.execute_historical_tests }}'):
            self.assertIn(wanted, text)
        for forbidden in ('  push:', '  pull_request:', '  schedule:', 'secrets.',
                          'ANTHROPIC_API_KEY', '--allow-paid-api', '--l2-model', '--l3-model'):
            self.assertNotIn(forbidden, text)
        audit = (ROOT / 'src/adaptive_llm_router/bugsinpy_tornado_readiness.py').read_text()
        self.assertNotIn('call_anthropic', audit)
        self.assertNotIn('urlopen', audit)


if __name__ == '__main__':
    unittest.main()
