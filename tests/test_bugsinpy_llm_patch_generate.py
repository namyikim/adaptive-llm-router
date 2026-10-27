"""No-network tests of opt-in generation protocol."""
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.bugsinpy_llm_patch_generate import prepare, extract_patch, main, selected_buggy_excerpt
from adaptive_llm_router.bugsinpy_reproduce import EXPECTED_COMMITS, ReplayError

class PatchPromptTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.source=self.root/"buggy"
        (self.source/"tqdm").mkdir(parents=True)
        (self.source/"tqdm/_tqdm.py").write_text("def broken(): return 0\n")
        for args in (["init", "-q"], ["add", "."],
                     ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                      "commit", "-qm", "synthetic source"]):
            subprocess.run(["git", "-C", str(self.source), *args], check=True,
                           capture_output=True, timeout=20)
        self.sha = subprocess.check_output(["git", "-C", str(self.source), "rev-parse", "HEAD"],
                                           text=True, timeout=20).strip()
        pins = patch.dict(EXPECTED_COMMITS, {"tqdm-6": (self.sha, "f" * 40)})
        pins.start()
        self.addCleanup(pins.stop)
        self.failure=self.root/"failure.txt"
        self.failure.write_text("AttributeError from buggy reproduction")

    def test_pinned_buggy_only(self):
        rec=prepare("tqdm-6",self.source,self.failure.read_text())
        self.assertIn("def broken()",rec["prompt"])
        self.assertNotIn("fixed_commit",rec["prompt"])
        self.assertEqual(rec["input_sha256"],hashlib.sha256(rec["prompt"].encode()).hexdigest())
        with patch("adaptive_llm_router.bugsinpy_llm_patch_generate.subprocess.check_output",
                   return_value="f"*40):
            with self.assertRaises(ReplayError):
                prepare("tqdm-6",self.source,self.failure.read_text())

    def test_validated_unified_diff_only(self):
        good=("diff --git a/tqdm/_tqdm.py b/tqdm/_tqdm.py\n"
              "--- a/tqdm/_tqdm.py\n+++ b/tqdm/_tqdm.py\n"
              "@@ -1 +1 @@\n-def broken(): return 0\n+def broken(): return 1\n")
        self.assertEqual(extract_patch(good,"tqdm-6"),good.encode())
        with self.assertRaises(ReplayError):
            extract_patch("I solved it, trust me","tqdm-6")
        with self.assertRaises(ReplayError):
            extract_patch(good.replace("tqdm/_tqdm.py","tqdm/tests/test.py"),"tqdm-6")

    def test_extract_diff_from_explanatory_fenced_answer(self):
        diff = ("diff --git a/tqdm/_tqdm.py b/tqdm/_tqdm.py\n"
                "--- a/tqdm/_tqdm.py\n+++ b/tqdm/_tqdm.py\n"
                "@@ -1 +1 @@\n-old\n+new\n")
        answer = "Suggested change:\n\n" + chr(96)*3 + "diff\n" + diff + chr(96)*3 + "\n"
        self.assertEqual(extract_patch(answer, "tqdm-6"), diff.encode())
        self.assertEqual(extract_patch(
            "Here is the diff:\n" + diff + "\nExplanation: improves handling.",
            "tqdm-6"), diff.encode())
        with self.assertRaises(ReplayError):
            extract_patch("It should use __len__. I cannot produce a diff.", "tqdm-6")
        with self.assertRaises(ReplayError):
            extract_patch(
                "The fix is:\n" + diff.replace("tqdm/_tqdm.py", "tqdm/tests/test_bad.py"),
                "tqdm-6",
            )

    def test_buggy_source_excerpt_reaches_relevant_method_after_prefix(self):
        long_buggy = "import os\n" + "x = 1\n" * 4300 + "def __len__(self):\n    return self.total\n"
        selected = selected_buggy_excerpt(long_buggy, "tqdm-6")
        self.assertIn("def __len__", selected)
        self.assertIn("return self.total", selected)
        self.assertLessEqual(len(selected), 18000)

    def test_cli_dry_run_never_calls_paid_api(self):
        out=self.root/"result"
        with patch.object(sys,"argv",[
            "patch-generate","--case-id","tqdm-6",
            "--buggy-checkout",str(self.source),
            "--failure-file",str(self.failure),
            "--output-root",str(out)
        ]), patch("adaptive_llm_router.bugsinpy_llm_patch_generate.call_anthropic",
                  side_effect=AssertionError("must not call")):
            main()
        import json
        report=json.loads((out/"generation_report.json").read_text())
        self.assertEqual(report["status"],"dry_run_no_api_calls")
        self.assertFalse(report["paid_enabled"])
        self.assertFalse(report["results"])
        self.assertTrue((out/"prompt.txt").is_file())
        self.assertTrue((out/"source_manifest.json").is_file())
        self.assertEqual(report["source_context_version"], "full-pinned-files-v2")

if __name__=="__main__":
    unittest.main()
