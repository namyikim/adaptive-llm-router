"""CPU-only audit tests: numerical equality is not checkpoint attestation."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.legacy_result_audit import audit_results, audit_folder

P = {"l1": .1, "l2": .6, "l3": .3}
Q = {"l1": .2, "l2": .55, "l3": .25}


def record(case_id, label, probabilities=P, attested=False, sha="same-sha", status="proposed"):
    tier = max(probabilities, key=probabilities.__getitem__)
    result = {
        "id": case_id, "model_label": label, "input_sha256": sha,
        "status": status,
        "decision": {"probabilities": probabilities, "proposed_tier": tier,
                     "tier": tier, "p_max": max(probabilities.values())},
    }
    if attested:
        ref = "jaredpalmer/" + label
        result["server_identity"] = {
            "checkpoint_run": ref, "reported_run": ref, "verified": True}
    return result


class HistoricalAuditTests(unittest.TestCase):
    def test_identical_historical_vectors_flagged_as_unattested(self):
        rows = [record(i, label) for i in ("bug-1", "bug-2")
                for label in ("kev-4b@v1.0", "kev-9b@v1.0")]
        report = audit_results(rows)
        self.assertEqual(report["n_valid_pairs"], 2)
        self.assertEqual(report["n_exact_probability_vector_matches"], 2)
        self.assertEqual(report["n_exact_pmax_matches"], 2)
        self.assertEqual(report["n_both_checkpoint_identities_attested"], 0)
        self.assertIn("all_probability_vectors_identical", report["flags"])
        self.assertEqual(report["status"], "historical_unattested_comparison")

    def test_equal_means_do_not_prove_same_vectors(self):
        rows = [
            record("bug-1", "kev-4b@v1.0", P),
            record("bug-1", "kev-9b@v1.0", Q),
            record("bug-2", "kev-4b@v1.0", Q),
            record("bug-2", "kev-9b@v1.0", P),
        ]
        report = audit_results(rows)
        self.assertEqual(report["n_exact_probability_vector_matches"], 0)
        self.assertEqual(report["n_exact_pmax_matches"], 0)
        self.assertEqual(report["models"]["kev-4b@v1.0"]["mean_p_max"],
                         report["models"]["kev-9b@v1.0"]["mean_p_max"])
        self.assertEqual(report["n_final_tier_matches"], 2)
        self.assertEqual(len(report["differing_examples"]), 2)

    def test_mismatched_hash_skipped_and_duplicate_reported(self):
        rows = [
            record("a", "kev-4b@v1.0", sha="right"),
            record("a", "kev-4b@v1.0", sha="right"),
            record("a", "kev-9b@v1.0", sha="wrong"),
        ]
        cases = [{"id": "a", "input_sha256": "right"}]
        report = audit_results(rows, cases=cases)
        self.assertEqual(report["n_invalid_or_mismatched_rows"], 1)
        self.assertEqual(report["n_duplicate_model_case_keys"], 1)
        self.assertEqual(report["n_valid_pairs"], 0)
        self.assertEqual(report["n_missing_or_failed_pairs"], 1)

    def test_attested_identity_only_counts_when_both_pinned(self):
        rows = [record("a", "kev-4b@v1.0", attested=True),
                record("a", "kev-9b@v1.0", attested=True)]
        report = audit_results(rows)
        self.assertEqual(report["status"], "verified_checkpoint_pairs")
        self.assertEqual(report["n_both_checkpoint_identities_attested"], 1)
        rows[1]["server_identity"]["reported_run"] = "jaredpalmer/kev-4b@v1.0"
        report = audit_results(rows)
        self.assertEqual(report["n_both_checkpoint_identities_attested"], 0)
        self.assertEqual(report["status"], "historical_unattested_comparison")

    def test_routing_failures_excluded(self):
        rows = [record("a", "kev-4b@v1.0"),
                record("a", "kev-9b@v1.0", status="failed")]
        report = audit_results(rows)
        self.assertEqual(report["n_valid_pairs"], 0)
        self.assertEqual(report["n_missing_or_failed_pairs"], 1)

    def test_reads_saved_run_without_network_or_gpu(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "outputs"
            out.mkdir()
            (root / "logs").mkdir()
            (root / "logs" / "kev_server.log").write_text(
                "Startup --run jaredpalmer/kev-9b@v1.0\n"
                "Startup --run jaredpalmer/kev-4b@v1.0\n"
            )
            with (out / "bugsinpy_kev_decisions.jsonl").open("w") as fp:
                for label in ("kev-4b@v1.0", "kev-9b@v1.0"):
                    fp.write(json.dumps(record("a", label)) + "\n")
                fp.write("{bad json\n")
            (out / "bugsinpy_cases.jsonl").write_text(
                json.dumps({"id": "a", "input_sha256": "same-sha"}) + "\n"
            )
            report = audit_folder(root)
            self.assertEqual(report["n_valid_pairs"], 1)
            self.assertEqual(report["input_parse_errors"]["decisions"][0]["line"], 3)
            self.assertEqual(report["requested_checkpoint_mentions_in_log"]["kev-4b@v1.0"], 1)
            self.assertIn("NOT actual per-request attestation", report["log_evidence_note"])

    def test_missing_files_are_reported_not_fabricated(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = audit_folder(Path(tmp))
            self.assertEqual(report["n_valid_pairs"], 0)
            self.assertEqual(report["status"], "insufficient_paired_data")
            self.assertEqual(report["input_parse_errors"]["cases"][0]["reason"], "missing_file")


if __name__ == "__main__":
    unittest.main()
