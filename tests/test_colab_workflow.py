"""Guard Colab Drive-first persistence against regressions."""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks" / "kev_a100_colab.ipynb"


class ColabPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        cls.cells = cls.notebook["cells"]
        cls.sources = ["".join(c["source"]) for c in cls.cells]

    def _cell(self, marker: str):
        results = [(i, text) for i, text in enumerate(self.sources) if marker in text]
        self.assertEqual(len(results), 1, marker)
        return results[0]

    def test_kev_9b_pinned_and_gpu_memory_checked(self):
        all_text = "\\n".join(self.sources)
        self.assertIn('KEV_MODEL_REF = "jaredpalmer/kev-9b@v1.0"', all_text)
        self.assertIn('"--run", KEV_MODEL_REF', all_text)
        self.assertIn('GPU_MEMORY_MIB < 30000', all_text)
        self.assertIn('"jaredpalmer/kev-4b@v1.0"', all_text)
        self.assertIn("RUN_BUGSINPY_COMPARE = True", all_text)
        self.assertIn('"kev_model_ref": KEV_MODEL_REF', all_text)

    def test_drive_self_test_before_model_load(self):
        mount_idx, mount = self._cell('drive.mount("/content/drive")')
        server_idx, _ = self._cell('log_path = RUN_ROOT / "logs" / "kev_server.log"')
        self.assertLess(mount_idx, server_idx)
        self.assertIn('"DRIVE_WRITE_VERIFIED.json"', mount)
        self.assertIn('verify_path.read_text(', mount)
        self.assertIn('"LATEST_RUN.txt"', mount)

    def test_all_code_cells_compile(self):
        for idx, cell in enumerate(self.cells):
            if cell["cell_type"] == "code":
                with self.subTest(cell=idx):
                    ast.parse(self.sources[idx], filename=f"colab-cell-{idx}")

    def test_drive_is_mounted_before_outputs_and_kev_server_start(self):
        mounted_idx, mounted = self._cell('drive.mount("/content/drive")')
        _, gpu = self._cell('gpu = subprocess.run(["nvidia-smi"')
        outputs_idx, output_setup = self._cell('ROOT = Path("/content/adaptive-llm-router")')
        server_idx, server = self._cell('log_path = RUN_ROOT / "logs" / "kev_server.log"')
        self.assertLess(mounted_idx, outputs_idx)
        self.assertLess(mounted_idx, server_idx)
        self.assertLess(self.sources.index(gpu), mounted_idx)
        self.assertIn('OUTPUTS = RUN_ROOT / "outputs"', mounted)
        self.assertIn('OUTPUTS.mkdir(parents=True, exist_ok=False)', mounted)
        self.assertIn('RUN_STATUS_PATH = RUN_ROOT / "RUN_STATUS.json"', mounted)
        self.assertNotIn('Path("/content/outputs")', output_setup)
        self.assertIn('log_path = RUN_ROOT / "logs" / "kev_server.log"', server)

    def test_write_through_results_on_drive(self):
        selectors = [
            self._cell("kev_sample_choices.json"),
            self._cell('str(OUTPUTS / "router_demo.json")'),
            self._cell('bench_out = OUTPUTS / "kev_devtools_benchmark"'),
            self._cell('gateway_selection_path = OUTPUTS / "kev_gateway_selection.json"'),
            self._cell('RUN_PAID_GATEWAY_TEST = False'),
            self._cell('RUN_HTTP_GATEWAY_TEST = False'),
        ]
        last_idx, finish = self._cell('archive_path = shutil.make_archive(str(root / "kev_gpu_results")')
        self.assertTrue(all(i < last_idx for i, _ in selectors))
        self.assertTrue(all("OUTPUTS" in s for _, s in selectors))
        for name in ("router_demo.json", "kev_gateway_selection.json",
                     "kev_gateway_claude_test.json", "kev_gateway_http_test.json",
                     "SAVE_COMPLETE.json"):
            self.assertIn(name, finish)
        self.assertIn('root, outputs = RUN_ROOT, OUTPUTS', finish)
        self.assertNotIn("shutil.copytree(", finish)
        self.assertLess(finish.index("shutil.make_archive("), finish.index("SAVE_COMPLETE.json"))
        self.assertIn('record_stage("run_finished"', finish)

    def test_paid_calls_off_and_analysis_text_opt_in(self):
        _, paid = self._cell("RUN_PAID_GATEWAY_TEST = False")
        _, http = self._cell("RUN_HTTP_GATEWAY_TEST = False")
        self.assertIn("SAVE_PAID_ANALYSIS_TEXT = False", paid)
        self.assertIn("if SAVE_PAID_ANALYSIS_TEXT:", paid)
        self.assertIn('paid_gateway_record = {"status": "skipped"', paid)
        self.assertIn('http_gateway_record = {"status": "skipped"', http)

    def test_default_runall_never_opens_browser_download(self):
        _, zip_cell = self._cell("DOWNLOAD_RESULTS_ZIP = False")
        self.assertIn("if DOWNLOAD_RESULTS_ZIP:", zip_cell)
        self.assertIn("files.download(archive)", zip_cell)

    def test_run_status_records_multiple_stages(self):
        _, mount = self._cell('RUN_STATUS_PATH = RUN_ROOT / "RUN_STATUS.json"')
        self.assertIn('RUN_STAGES[stage]', mount)
        self.assertIn("RUN_STATUS_PATH.write_text(", mount)
        all_text = "\n".join(self.sources)
        for stage in ("drive_mounted", "kev_server_ready", "sample_choices", "router_demo",
                      "kev_gateway_selection", "claude_gateway_test", "http_gateway_test",
                      "run_finished"):
            with self.subTest(stage=stage):
                self.assertIn(f'record_stage("{stage}"', all_text)


if __name__ == "__main__":
    unittest.main()
