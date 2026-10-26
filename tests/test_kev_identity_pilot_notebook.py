"""Regression tests: the 10-case A100 pilot validates BOTH live Kev checkpoints."""
import ast
import json
import unittest
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks" / "kev_identity_10_case_colab.ipynb"


class KevIdentityPilotNotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        cls.code = [("".join(c["source"])) for c in cls.notebook["cells"]
                    if c["cell_type"] == "code"]
        cls.text = "\n".join(cls.code)

    def test_all_code_cells_parse(self):
        self.assertEqual(len(self.code), 5)
        for i, source in enumerate(self.code):
            with self.subTest(cell=i):
                ast.parse(source)

    def test_uses_saved_cases_without_rerunning_historical_projects(self):
        self.assertIn('SOURCE_RUN_ID = "kev_a100_20261026_083544_UTC_c09a65"', self.text)
        self.assertIn('SOURCE_CASES = SOURCE_RUN / "outputs/bugsinpy_cases.jsonl"', self.text)
        self.assertIn('while len(selected) < 10', self.text)
        self.assertIn('if len(selected) != 10:', self.text)
        self.assertIn('source_100_cases_sha256', self.text)
        self.assertNotIn('collect_cases(', self.text)
        self.assertNotIn('bugsinpy-checkout', self.text)
        self.assertNotIn('RUN_PAID_GATEWAY_TEST = True', self.text)

    def test_server_identity_attestation_gate_and_fail_closed(self):
        self.assertIn('probe_model_identity(BASE_URL, label)', self.text)
        self.assertIn('"jaredpalmer/" + label', self.text)
        self.assertIn('collect_decisions(', self.text)
        self.assertIn('status_file = PILOT_ROOT / "RUN_STATUS.json"', self.text)
        self.assertIn('if analysis["n_paired"] != len(selected):', self.text)
        self.assertIn('if proofs["kev-4b@v1.0"]["reported_run"] == proofs["kev-9b@v1.0"]["reported_run"]:', self.text)
        self.assertIn('stop_checkpoint(active)', self.text)

    def test_probability_equality_audit_and_drive_persistence(self):
        self.assertIn('exact_probability_vector_match_count', self.text)
        self.assertIn('model_attestations.json', self.text)
        self.assertIn('pilot_comparison.json', self.text)
        self.assertIn('pilot_summary.json', self.text)
        self.assertIn('SAVE_COMPLETE.json', self.text)
        self.assertIn('pilot_decisions.jsonl', self.text)
        self.assertIn('checkpoint_attestations', self.text)
        self.assertIn('drive.mount("/content/drive")', self.text)


if __name__ == "__main__":
    unittest.main()
