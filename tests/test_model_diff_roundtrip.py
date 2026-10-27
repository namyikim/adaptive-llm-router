"""Protocol coverage, NOT model quality: 200 synthetic diffs and real Git."""
import difflib
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.bugsinpy_llm_patch_generate import extract_patch


class SyntheticDiffRoundtripTests(unittest.TestCase):
    def test_two_hundred_deterministic_patch_bodies_roundtrip_losslessly(self):
        rng = random.Random(20261027)
        fence = chr(96) * 3
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "tqdm").mkdir()
            source = root / "tqdm/_tqdm.py"
            for trial in range(200):
                with self.subTest(trial=trial):
                    before = [f"line_{i}_{rng.randrange(100)}\n"
                              for i in range(rng.randrange(1, 60))]
                    after = before.copy()
                    start = rng.randrange(len(after))
                    end = rng.randrange(start, len(after) + 1)
                    after[start:end] = [f"new_{trial}_{j}\n"
                                        for j in range(rng.randrange(1, 8))]
                    diff = ("diff --git a/tqdm/_tqdm.py b/tqdm/_tqdm.py\n"
                            + "".join(difflib.unified_diff(
                                before, after, fromfile="a/tqdm/_tqdm.py",
                                tofile="b/tqdm/_tqdm.py")))
                    response = "Proposed patch:\n" + fence + "diff\n" + diff + fence + "\nDone."
                    candidate = extract_patch(response, "tqdm-6")
                    self.assertEqual(candidate, diff.encode("utf-8"))
                    source.write_text("".join(before), encoding="utf-8")
                    result = subprocess.run(["git", "apply", "-"], cwd=root,
                                            input=candidate, capture_output=True,
                                            timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr.decode())
                    self.assertEqual(source.read_text(encoding="utf-8"), "".join(after))


if __name__ == "__main__":
    unittest.main()
