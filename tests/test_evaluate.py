import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.evaluate import read_cases, summarize


class EvaluationTests(unittest.TestCase):
    def test_read_cases(self):
        path = Path(__file__).resolve().parents[1] / "benchmarks" / "data" / "demo_routing.jsonl"
        cases = read_cases(path)
        self.assertEqual(len(cases), 12)
        self.assertEqual({c["label"] for c in cases}, {"l1", "l2", "l3"})

    def test_summary(self):
        report = summarize([
            {"prediction": "l1", "label": "l1", "uncertain": False},
            {"prediction": "l2", "label": "l1", "uncertain": True},
        ])
        self.assertEqual(report["n"], 2)
        self.assertEqual(report["illustrative_label_agreement"], 0.5)
        self.assertEqual(report["confusion"]["l1"]["l2"], 1)


if __name__ == "__main__":
    unittest.main()
