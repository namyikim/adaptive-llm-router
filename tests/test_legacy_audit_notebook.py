"""Guard the CPU-only historical-run audit notebook."""
import ast
import json
import unittest
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks" / "audit_existing_kevs_colab.ipynb"


class HistoricalAuditNotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        cls.cells = cls.nb["cells"]

    def test_every_code_cell_compiles(self):
        for idx, cell in enumerate(self.cells):
            if cell["cell_type"] == "code":
                with self.subTest(cell=idx):
                    ast.parse("".join(cell["source"]))

    def test_reads_existing_results_without_restarting_gpu(self):
        code = "\n".join("".join(c["source"]) for c in self.cells)
        self.assertIn('TARGET_RUN_ID = ""', code)
        self.assertIn('completed_100 = ', code)
        self.assertIn('from adaptive_llm_router.legacy_result_audit import audit_folder', code)
        self.assertIn('report = audit_folder(RUN_ROOT)', code)
        self.assertIn('bugsinpy_legacy_audit.json', code)
        self.assertNotIn('kev.serve', code)
        self.assertNotIn('uv sync', code)
        self.assertNotIn('nvidia-smi', code)
        self.assertNotIn('collect_decisions(', code)


if __name__ == "__main__":
    unittest.main()
