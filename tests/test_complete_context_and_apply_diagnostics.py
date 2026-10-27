"""Real Git fixtures for context completeness and patch diagnostics; no API/Docker."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router import bugsinpy_llm_patch_generate as generation
from adaptive_llm_router import bugsinpy_patch_verifier as verification


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True,
                                   stderr=subprocess.PIPE, timeout=20).strip()


def commit_source(root, source):
    (root / "tqdm").mkdir(parents=True)
    (root / "tqdm/_tqdm.py").write_text(source, encoding="utf-8")
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "synthetic buggy source; no project execution")
    return git(root, "rev-parse", "HEAD")


class CompleteSourceContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # The first constructor belongs to another class. The relevant
        # constructor branch falls outside every old 2,500-character window.
        self.source = ("class Other:\n    def __init__(self):\n        pass\n"
                       + "# unrelated padding\n" * 1600
                       + "class tqdm:\n    def __init__(self, disable=False):\n"
                       + "        # constructor documentation\n" * 150
                       + "        if disable:\n            self.disable = disable\n"
                       + "            return  # required_early_return_context\n"
                       + "        # more constructor body\n" * 150
                       + "    def __len__(self):\n        return self.total\n"
                       + "# trailing module documentation\n" * 150)
        self.sha = commit_source(self.root, self.source)

    def prepare(self):
        with patch.dict(generation.EXPECTED_COMMITS,
                        {"tqdm-6": (self.sha, "f" * 40)}):
            return generation.prepare("tqdm-6", self.root, "Missing total attribute")

    def test_complete_constructor_and_all_original_source_are_in_prompt(self):
        request = self.prepare()
        self.assertIn("required_early_return_context", request["prompt"])
        self.assertIn(self.source, request["prompt"])
        self.assertNotIn("historical buggy source excerpt omitted", request["prompt"])

    def test_source_manifest_matches_full_pinned_bytes_and_original_line_count(self):
        request = self.prepare()
        manifest = request.get("source_manifest")
        self.assertIsInstance(manifest, list, "Need explicit source completeness evidence")
        self.assertEqual(len(manifest), 1)
        entry = manifest[0]
        self.assertEqual(entry["path"], "tqdm/_tqdm.py")
        self.assertTrue(entry["complete"])
        self.assertEqual(entry["source_sha256"], hashlib.sha256(self.source.encode()).hexdigest())
        self.assertEqual(entry["line_count"], len(self.source.splitlines()))
        constructor = next(x for x in entry["definitions"] if x["name"] == "tqdm.__init__")
        expected_line = self.source.splitlines().index("    def __init__(self, disable=False):") + 1
        self.assertEqual(constructor["start_line"], expected_line)
        self.assertIn("original file line numbers", request["prompt"])

    def test_dirty_checkout_cannot_replace_pinned_buggy_source(self):
        (self.root / "tqdm/_tqdm.py").write_text("# DO_NOT_USE_DIRTY_WORKTREE\n")
        request = self.prepare()
        self.assertIn(self.source, request["prompt"])
        self.assertNotIn("DO_NOT_USE_DIRTY_WORKTREE", request["prompt"])


class ApplyFailureEvidenceTests(unittest.TestCase):
    def test_real_git_failure_is_separate_from_environment_and_preserves_patch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "work"
            repo = workspace / "repos/tqdm"
            repo.mkdir(parents=True)
            sha = commit_source(repo, "value = 1\n")
            fixed = root / "fixed"
            (fixed / "tqdm/tests").mkdir(parents=True)
            (fixed / "tqdm/tests/tests_synchronisation.py").write_text("# verifier fixture\n")
            candidate = root / "candidate.diff"
            raw = ("diff --git a/tqdm/_tqdm.py b/tqdm/_tqdm.py\n"
                   "--- a/tqdm/_tqdm.py\n+++ b/tqdm/_tqdm.py\n"
                   "@@ -1 +1 @@\n-value = 999\n+value = 2\n").encode()
            candidate.write_bytes(raw)
            record = {"case_id": "tqdm-6", "project": "tqdm",
                      "buggy_commit": sha, "fixed_commit_for_verifier_only": "f" * 40,
                      "docker_image": "fixture", "test_commands": [["python", "-m", "pytest", "test.py"]]}
            original_run = subprocess.run

            def commands(args, **kwargs):
                if args[:3] == ["docker", "image", "inspect"]:
                    return subprocess.CompletedProcess(args, 0, b"[]", b"")
                return original_run(args, **kwargs)

            with patch.object(verification, "prepare_metadata", return_value=record), \
                 patch.object(verification, "checkout_versions", return_value={"buggy": repo, "fixed": fixed}), \
                 patch.object(verification, "_test_one", side_effect=[{"verdict": "test_failure"}, {"verdict": "pass"}]) as tests, \
                 patch.object(verification.subprocess, "run", side_effect=commands):
                report = verification.verify_patch(dataset_root=root, workspace=workspace,
                    output_root=root / "results", case_id="tqdm-6", tier="l3",
                    model_id="fixture-model", patch_file=candidate, execute=True)
            self.assertEqual(report["status"], "patch_apply_failed")
            self.assertEqual(report["failure_stage"], "patch_apply_check")
            self.assertIsNone(report["regression_passed"])
            self.assertFalse(report["candidate_test_executed"])
            self.assertEqual(tests.call_count, 2, "No candidate test after an inapplicable diff")
            evidence = report["patch_application"]
            self.assertNotEqual(evidence["returncode"], 0)
            log = (root / "results" / evidence["log_file"]).read_text()
            self.assertIn("patch does not apply", log)
            self.assertEqual(candidate.read_bytes(), raw)
            self.assertEqual((repo / "tqdm/_tqdm.py").read_text(), "value = 1\n")
            saved = json.loads((root / "results/tqdm-6_l3.json").read_text())
            self.assertEqual(saved["status"], "patch_apply_failed")


if __name__ == "__main__":
    unittest.main()
