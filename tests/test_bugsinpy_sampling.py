"""Deterministic project-balanced BugsInPy sampling without downloading models."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.bugsinpy_sampling import available_bugs, manifest, stratified_plan


class SamplingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for project, n in (("alpha", 8), ("beta", 5), ("gamma", 2)):
            root = self.root / "projects" / project
            root.mkdir(parents=True)
            (root / "project.info").write_text('github_url="https://github.com/a/b"\n')
            for i in range(1, n + 1):
                bug = root / "bugs" / str(i)
                bug.mkdir(parents=True)
                (bug / "bug.info").write_text(f'buggy_commit_id="sha{i}"\n')

    def test_metadata_enumeration_and_deterministic_selection(self):
        opts = available_bugs(self.root, ("alpha", "beta", "gamma"))
        self.assertEqual(len(opts["alpha"]), 8)
        a = stratified_plan(self.root, seed=123, projects=("alpha", "beta", "gamma"), max_per_project=3)
        b = stratified_plan(self.root, seed=123, projects=("alpha", "beta", "gamma"), max_per_project=3)
        c = stratified_plan(self.root, seed=124, projects=("alpha", "beta", "gamma"), max_per_project=3)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 8)
        self.assertEqual(set(x[0] for x in a[:3]), {"alpha", "beta", "gamma"})
        self.assertEqual(len(set(a)), len(a))
        self.assertNotEqual(a, c)

    def test_manifest_has_counts_checksum_and_stable_id_order(self):
        kw = dict(seed=123, projects=("alpha", "beta"), target_successes=7, max_per_project=4)
        a = manifest(self.root, **kw)
        b = manifest(self.root, **kw)
        self.assertEqual(a, b)
        self.assertEqual(a["candidate_count"], 8)
        self.assertEqual(a["sampled_projects"], {"alpha": 4, "beta": 4})
        self.assertEqual(len(a["metadata_sha256"]), 64)
        self.assertEqual(a["target_successes"], 7)
        self.assertEqual(len(a["candidate_ids_in_attempt_order"]), 8)

    def test_does_not_infer_bug_severity(self):
        m = manifest(self.root, projects=("gamma",), target_successes=2)
        self.assertNotIn("severity", m)
        self.assertIn("no stratification by actual bug severity", m["note"])

    def test_invalid_options(self):
        with self.assertRaises(ValueError):
            stratified_plan(self.root, projects=("alpha",), max_per_project=0)
        with self.assertRaises(ValueError):
            manifest(self.root, projects=("alpha",), target_successes=0)
        with self.assertRaises(ValueError):
            stratified_plan(self.root, projects=("../",))

    def test_missing_metadata_projects_are_skipped(self):
        plan = stratified_plan(self.root, projects=("unknown", "gamma"))
        self.assertEqual(len(plan), 2)
        self.assertEqual(set(p for p, _ in plan), {"gamma"})


if __name__ == "__main__":
    unittest.main()
