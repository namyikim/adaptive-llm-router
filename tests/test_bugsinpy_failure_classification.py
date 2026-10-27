"""Real tqdm-6 regression log classifier; CPU tests do not execute Docker."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.bugsinpy_reproduce import (
    REPRODUCED, classify_test_output, classify_reproduction,
)


class PytestOutcomeClassificationTests(unittest.TestCase):
    def test_real_tqdm_6_traceback_excerpt_is_not_environment_error(self):
        # Source and failure summary from GH Actions run #40428395903.
        buggy_output = """
============================= test session starts ==============================
collected 1 item
tqdm/tests/tests_synchronisation.py F                                    [100%]

=================================== FAILURES ===================================
__________________________________ test_imap ___________________________________
    @with_setup(pretest, posttest)
    def test_imap():
        try:
            from multiprocessing import Pool
        except ImportError:
            raise SkipTest
        pool = Pool()
>       res = list(tqdm(pool.imap(incr, range(100)), disable=True))
tqdm/tests/tests_synchronisation.py:180:
    def __len__(self):
>       else self.total)
E       AttributeError: 'tqdm' object has no attribute 'total'
=========================== short test summary info ============================
FAILED tqdm/tests/tests_synchronisation.py::test_imap - AttributeError: 'tqdm' object has no attribute 'total'
======================== 1 failed, 4 warnings in 0.21s =========================
"""
        buggy = classify_test_output(1, buggy_output)
        fixed = classify_test_output(0, "collected 1 item\n1 passed in 0.15s")
        self.assertEqual(buggy, "test_failure")
        self.assertEqual(fixed, "pass")
        self.assertEqual(classify_reproduction(
            [{"verdict": buggy}], [{"verdict": fixed}]), REPRODUCED)

    def test_real_missing_original_tqdm_test_is_not_reproduced(self):
        no_test = ("collected 0 items\n"
                   "ERROR: not found: /src/tqdm/tests/tests_synchronisation.py::test_imap\n")
        self.assertEqual(classify_test_output(4, no_test), "test_not_collected")

    def test_real_environment_errors_stay_environment_errors(self):
        cases = [
            "ERROR collecting tests/test_x.py\nE ModuleNotFoundError: No module named 'demo'",
            "E   ModuleNotFoundError: No module named 'pytest'",
            "Traceback (most recent call last):\nImportError: No module named x",
            "FAILED test_foo.py::test_x - ModuleNotFoundError: No module named x",
            "INTERNALERROR> failed during collection",
            "SyntaxError: invalid syntax",
        ]
        for sample in cases:
            with self.subTest(output=sample):
                self.assertEqual(classify_test_output(1, sample), "environment_failure")

    def test_unknown_errors_are_not_assumed_to_be_test_failures(self):
        self.assertEqual(classify_test_output(137, "docker: unable to allocate memory"),
                         "nonzero_unclassified")
        self.assertEqual(classify_test_output(1, "printed the word ImportError as text"),
                         "nonzero_unclassified")
        self.assertEqual(classify_test_output(1, "passed=0, unknown error"),
                         "nonzero_unclassified")

    def test_unittest_and_pytest_failure_samples(self):
        self.assertEqual(classify_test_output(
            1, "FAIL: test_my_case (my.case)\nAssertionError: expected"
            ), "test_failure")
        self.assertEqual(classify_test_output(
            1, "FAILED test_other.py::test_my_case - AssertionError: invalid output"
            ), "test_failure")


if __name__ == "__main__":
    unittest.main()
