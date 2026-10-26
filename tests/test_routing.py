import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.routing import cascade, next_tier, parse_route


class RoutingTests(unittest.TestCase):
    @staticmethod
    def response(p):
        return {"answers": {"start_tier": {"type": "choice", "probabilities": p}}, "latency_ms": 12.5}

    def test_confident(self):
        decision = parse_route(self.response({"l1": 0.8, "l2": 0.1, "l3": 0.1}))
        self.assertEqual(decision.tier, "l1")
        self.assertFalse(decision.uncertain)
        self.assertEqual(decision.latency_ms, 12.5)

    def test_uncertain_defaults_medium(self):
        decision = parse_route(self.response({"l1": 0.4, "l2": 0.35, "l3": 0.25}))
        self.assertEqual(decision.proposed_tier, "l1")
        self.assertEqual(decision.tier, "l2")
        self.assertTrue(decision.uncertain)

    def test_uncertain_l3_never_demoted(self):
        # Regression: previous L2 fallback changed correct L3 to L2.
        p = {"l1": 0.1141, "l2": 0.3020, "l3": 0.5839}
        result = parse_route(self.response(p), min_probability=0.65)
        self.assertEqual(result.proposed_tier, "l3")
        self.assertEqual(result.tier, "l3")
        self.assertTrue(result.uncertain)

    def test_uncertain_l2_remains_l2(self):
        result = parse_route(self.response({"l1": .10, "l2": .58, "l3": .32}))
        self.assertEqual(result.tier, "l2")

    def test_invalid_probabilities(self):
        with self.assertRaises(ValueError):
            parse_route(self.response({"l1": 0.5, "l2": 0.5}))

    def test_cascade_requires_verification(self):
        seen = []
        result = cascade(lambda tier: tier, lambda tier, answer: tier == "l3", "l1")
        self.assertEqual(result["status"], "verified")
        self.assertEqual([r["tier"] for r in result["attempts"]], ["l1", "l2", "l3"])

    def test_cascade_ends_with_review(self):
        result = cascade(lambda tier: tier, lambda tier, answer: False, "l2")
        self.assertEqual(result["status"], "review_required")
        self.assertIsNone(result["answer"])

    def test_escalate(self):
        self.assertEqual(next_tier("l1", externally_verified_pass=False), "l2")
        self.assertIsNone(next_tier("l2", externally_verified_pass=True))
        self.assertIsNone(next_tier("l3", externally_verified_pass=False))

    def test_verifier_must_be_boolean(self):
        with self.assertRaises(TypeError):
            cascade(lambda tier: 1, lambda tier, answer: "yes", "l1")


if __name__ == "__main__":
    unittest.main()
