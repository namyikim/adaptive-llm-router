"""Real parser and git-apply regression tests; no provider calls or Docker."""
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.bugsinpy_llm_patch_generate import extract_patch
from adaptive_llm_router.bugsinpy_reproduce import ReplayError


def modification(path="tqdm/_tqdm.py", old="old", new="new"):
    return (f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n+++ b/{path}\n"
            f"@@ -1 +1 @@\n-{old}\n+{new}\n")


class ModelDiffIntegrityTests(unittest.TestCase):
    def test_short_hunk_is_rejected_not_completed_by_guessing(self):
        malformed = modification().replace("@@ -1 +1 @@", "@@ -1,2 +1,2 @@")
        with self.assertRaises(ReplayError):
            extract_patch(malformed, "tqdm-6")

    def test_extra_edit_lines_are_not_silently_discarded(self):
        with self.assertRaises(ReplayError):
            extract_patch(modification() + "-second\n+replacement\n", "tqdm-6")

    def test_malformed_later_hunk_cannot_be_dropped(self):
        with self.assertRaises(ReplayError):
            extract_patch(modification() + "@@\n-second\n+replacement\n", "tqdm-6")

    def test_second_patch_after_prose_cannot_be_dropped(self):
        first = modification("tornado/ioloop.py")
        second = modification("tornado/platform/asyncio.py")
        with self.assertRaises(ReplayError):
            extract_patch(first + "Another change follows:\n" + second, "tornado-6")

    def test_two_fenced_candidates_are_ambiguous_not_first_one_wins(self):
        fence = chr(96) * 3
        first = modification("tornado/ioloop.py")
        second = modification("tornado/platform/asyncio.py")
        response = (fence + "diff\n" + first + fence + "\n\n"
                    + fence + "diff\n" + second + fence + "\n")
        with self.assertRaises(ReplayError):
            extract_patch(response, "tornado-6")

    def test_unclosed_fence_is_rejected(self):
        with self.assertRaises(ReplayError):
            extract_patch(chr(96) * 3 + "diff\n" + modification(), "tqdm-6")

    def test_missing_old_file_header_is_rejected(self):
        with self.assertRaises(ReplayError):
            extract_patch(modification().replace("--- a/tqdm/_tqdm.py\n", ""), "tqdm-6")

    def test_valid_multifile_patch_in_one_fence_keeps_every_file(self):
        diff = (modification("tornado/ioloop.py")
                + modification("tornado/platform/asyncio.py"))
        fence = chr(96) * 3
        self.assertEqual(extract_patch("Proposed change:\n" + fence + "diff\n"
                                      + diff + fence + "\nDone.", "tornado-6"),
                         diff.encode())

    def test_empty_added_line_and_no_newline_marker_preserved(self):
        diff = modification(old="value", new="")
        self.assertEqual(extract_patch(diff, "tqdm-6"), diff.encode())
        no_newline = ("diff --git a/tqdm/_tqdm.py b/tqdm/_tqdm.py\n"
                      "--- a/tqdm/_tqdm.py\n+++ b/tqdm/_tqdm.py\n"
                      "@@ -1 +1 @@\n-old\n\\ No newline at end of file\n"
                      "+new\n\\ No newline at end of file\n")
        self.assertEqual(extract_patch(no_newline, "tqdm-6"), no_newline.encode())

    def test_valid_patch_reaches_real_git_apply_without_touching_other_files(self):
        # A synthetic protocol fixture, NOT a model-generated BugsInPy success.
        diff = modification(old="value = 1", new="value = 2")
        raw = "Explanation before patch.\n" + diff + "\nExplanation after patch."
        digest = hashlib.sha256(raw.encode()).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "tqdm").mkdir()
            original = root / "tqdm/_tqdm.py"
            original.write_text("value = 1\n", encoding="utf-8")
            untouched = root / "sentinel.txt"
            untouched.write_text("unchanged", encoding="utf-8")
            patch = extract_patch(raw, "tqdm-6")
            for args in (["--check"], []):
                result = subprocess.run(["git", "apply", *args, "-"], input=patch,
                                        cwd=root, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(original.read_text(), "value = 2\n")
            self.assertEqual(untouched.read_text(), "unchanged")
        self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(), digest)

    def test_test_file_edit_is_still_rejected(self):
        with self.assertRaises(ReplayError):
            extract_patch(modification("tqdm/tests/test_x.py"), "tqdm-6")


if __name__ == "__main__":
    unittest.main()
