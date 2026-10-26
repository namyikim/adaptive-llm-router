"""Guard the Colab Run All workflow from saving stale output before gateway test."""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path


NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks" / "kev_a100_colab.ipynb"


class ColabRunAllTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        cls.cells = cls.notebook["cells"]
        cls.sources = ["".join(cell["source"]) for cell in cls.cells]

    def test_all_code_cells_are_valid_python(self):
        for i, cell in enumerate(self.cells):
            if cell["cell_type"] == "code":
                with self.subTest(cell=i):
                    ast.parse(self.sources[i], filename=f"colab-cell-{i}")

    def test_save_runs_after_all_gateway_steps(self):
        selections = [i for i, s in enumerate(self.sources) if 'gateway_selection_path = OUTPUTS / "kev_gateway_selection.json"' in s]
        paid = [i for i, s in enumerate(self.sources) if 'RUN_PAID_GATEWAY_TEST = False' in s]
        http = [i for i, s in enumerate(self.sources) if 'RUN_HTTP_GATEWAY_TEST = False' in s]
        saved = [i for i, s in enumerate(self.sources) if 'drive.mount("/content/drive")' in s]
        self.assertEqual(len(selections), 1)
        self.assertEqual(len(paid), 1)
        self.assertEqual(len(http), 1)
        self.assertEqual(len(saved), 1)
        self.assertLess(selections[0], paid[0])
        self.assertLess(paid[0], http[0])
        self.assertLess(http[0], saved[0])

    def test_save_has_all_gateway_results_and_fresh_archive(self):
        save = next(s for s in self.sources if 'drive.mount("/content/drive")' in s)
        for name in ("kev_gateway_selection.json", "kev_gateway_claude_test.json",
                     "kev_gateway_http_test.json", "router_demo.json", "SAVE_COMPLETE.json"):
            with self.subTest(name=name):
                self.assertIn(name, save)
        self.assertIn('shutil.copytree(outputs, root / "outputs")', save)
        self.assertIn('shutil.make_archive(str(root / "kev_gpu_results"), "zip", outputs)', save)
        self.assertLess(save.index('shutil.copytree('), save.index('shutil.make_archive('))
        self.assertLess(save.index('shutil.make_archive('), save.index('SAVE_COMPLETE.json'))

    def test_paid_calls_off_and_analysis_content_opt_in(self):
        paid = next(s for s in self.sources if 'RUN_PAID_GATEWAY_TEST = False' in s)
        http = next(s for s in self.sources if 'RUN_HTTP_GATEWAY_TEST = False' in s)
        self.assertIn('SAVE_PAID_ANALYSIS_TEXT = False', paid)
        self.assertIn('if SAVE_PAID_ANALYSIS_TEXT:', paid)
        self.assertIn('paid_gateway_record = {"status": "skipped"', paid)
        self.assertIn('http_gateway_record = {"status": "skipped"', http)

    def test_no_forced_download_during_runall(self):
        local_zip = next(s for s in self.sources if 'DOWNLOAD_RESULTS_ZIP = False' in s)
        self.assertIn('if DOWNLOAD_RESULTS_ZIP:', local_zip)
        self.assertIn('files.download(archive)', local_zip)


if __name__ == "__main__":
    unittest.main()
