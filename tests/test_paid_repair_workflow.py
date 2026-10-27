"""CPU contract: paid repair workflow is always opt-in."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
YAML = ROOT / ".github/workflows/bugsinpy-llm-repair-trial.yml"

class PaidRepairWorkflowTests(unittest.TestCase):
    def test_opt_in_gates_and_no_automatic_schedule(self):
        y = YAML.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", y)
        self.assertIn("allow_paid:", y)
        self.assertIn("execute_verifier:", y)
        self.assertGreaterEqual(y.count("default: false"), 2)
        self.assertIn("inputs.allow_paid && inputs.execute_verifier", y)
        self.assertIn("--allow-paid", y)
        self.assertIn("--execute-verifier", y)
        self.assertIn("secrets.ANTHROPIC_API_KEY", y)
        self.assertNotIn("schedule:", y)
        self.assertNotIn("push:", y)
        for case in ("tqdm-6","tornado-5","tornado-6",
                     "tornado-7","tornado-11","tornado-14"):
            self.assertIn("- " + case, y)

if __name__ == "__main__":
    unittest.main()
