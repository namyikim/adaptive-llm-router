import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.benchmark_verified import compare, evaluate_strategy, read_verified_cases


def make_case(identifier, kind, start="l1"):
    return {
        "id": identifier, "split": "test", "task_type": kind,
        "outcomes": {
            "l1": {"passed": False, "cost_usd": 0.01, "latency_ms": 10,
                   "verifier_cost_usd": 0.001, "verifier_latency_ms": 2},
            "l2": {"passed": True, "cost_usd": 0.04, "latency_ms": 40,
                   "verifier_cost_usd": 0.001, "verifier_latency_ms": 2},
            "l3": {"passed": True, "cost_usd": 0.15, "latency_ms": 100},
        },
        "predictions": {
            "kev": {"tier": start, "decision_cost_usd": 0.002, "decision_latency_ms": 4},
            "openai": {"tier": "l2", "decision_cost_usd": 0.003, "decision_latency_ms": 3},
        }
    }


class VerifiedBenchmarkTests(unittest.TestCase):
    def test_replay_includes_decision_verifier_and_escalation(self):
        data = [make_case("one", "log")]
        result = evaluate_strategy(data, backend="kev")
        self.assertEqual(result["verified_success_rate"], 1.0)
        self.assertEqual(result["escalation_rate"], 1.0)
        self.assertAlmostEqual(result["mean_total_cost_usd"], 0.054)
        self.assertEqual(result["p50_e2e_latency_ms"], 58)

    def test_comparison_without_fake_metrics(self):
        rows = [make_case("one", "log"), make_case("two", "code")]
        report = compare(rows)
        self.assertEqual(report["n"], 2)
        self.assertEqual(report["strategies"]["always_l3"]["mean_total_cost_usd"], 0.15)
        self.assertIn("openai", report["strategies"])
        self.assertIn("kev", report["strategies"])
        self.assertEqual(report["strategies"]["kev"]["success_delta_vs_always_l3"], 0)

    def test_missing_predictions_cannot_be_imputed(self):
        rows = [make_case("one", "log"), make_case("two", "code")]
        del rows[0]["predictions"]["openai"]
        report = compare(rows)
        self.assertNotIn("openai", report["strategies"])
        self.assertEqual(report["incomplete_backends"]["openai"], ["one"])
        with self.assertRaises(ValueError):
            evaluate_strategy(rows, backend="openai")

    def test_read_held_out_and_reject_invalid(self):
        row = make_case("case", "code")
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "verified.jsonl"
            file.write_text(json.dumps(row) + "\n", encoding="utf-8")
            self.assertEqual(len(read_verified_cases(file)), 1)
            row["split"] = "train"
            file.write_text(json.dumps(row) + "\n")
            with self.assertRaises(ValueError):
                read_verified_cases(file)
            row["split"] = "test"
            row["outcomes"]["l3"]["passed"] = "yes"
            file.write_text(json.dumps(row) + "\n")
            with self.assertRaises(ValueError):
                read_verified_cases(file)


if __name__ == "__main__":
    unittest.main()
