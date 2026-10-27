"""Regression tests grounded in the four-case Tornado Actions artifact.

Run 40437186598 incorrectly labeled 3 missing unittest methods as reproduced
bugs. No Docker or legacy Python is run by this CPU test suite.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.bugsinpy_reproduce import (
    classify_test_output, classify_reproduction, REPRODUCED,
)

MISSING_TEST_METHODS = {
    "tornado-5": ("test_clock_backwards", "TestPeriodicCallbackMath"),
    "tornado-11": ("test_chunked_request_uppercase", "HTTPServerRawTest"),
    "tornado-14": ("test_force_current", "TestIOLoopCurrent"),
}


class TornadoHistoricalMethodCollectionTests(unittest.TestCase):
    def test_three_real_missing_methods_are_uncollected_not_reproduced(self):
        for case_id, (method, cls) in MISSING_TEST_METHODS.items():
            with self.subTest(case_id=case_id):
                log = (
                    "======================================================================\n"
                    f"ERROR: {method} (unittest.loader._FailedTest)\n"
                    "----------------------------------------------------------------------\n"
                    f"AttributeError: type object '{cls}' has no attribute '{method}'\n"
                    "\n----------------------------------------------------------------------\n"
                    "Ran 1 test in 0.000s\n\nFAILED (errors=1)\n"
                )
                observed = classify_test_output(1, log)
                self.assertEqual(observed, "test_not_collected")
                self.assertEqual(
                    classify_reproduction([{"verdict": observed}], [{"verdict": "pass"}]),
                    "environment_or_timeout",
                )

    def test_missing_class_still_uncollected(self):
        original = (
            "ERROR: LeakTest (unittest.loader._FailedTest)\n"
            "AttributeError: module 'tornado.test.asyncio_test' has no attribute 'LeakTest'\n"
            "Ran 1 test in 0.000s\nFAILED (errors=1)"
        )
        self.assertEqual(classify_test_output(1, original), "test_not_collected")

    def test_genuine_tornado7_exception_is_reproduced(self):
        buggy = (
            "ERROR:tornado.application:Multiple exceptions in yield list\n"
            "TypeError: object Future can't be used in 'await' expression\n"
            "ERROR: test_run_in_executor_native (tornado.test.ioloop_test.TestIOLoopFutures)\n"
            "Traceback (most recent call last):\n"
            "TypeError: object Future can't be used in 'await' expression\n"
            "Ran 1 test in 0.002s\nFAILED (errors=1)"
        )
        self.assertEqual(classify_test_output(1, buggy), "test_failure")
        self.assertEqual(
            classify_reproduction([{"verdict": "test_failure"}], [{"verdict": "pass"}]),
            REPRODUCED,
        )

    def test_real_dependency_failure_is_not_masked_as_missing_test_method(self):
        log = (
            "ERROR: test_force_current (unittest.loader._FailedTest)\n"
            "ModuleNotFoundError: No module named 'six'\nFAILED (errors=1)"
        )
        self.assertEqual(classify_test_output(1, log), "environment_failure")

    def test_missing_unrelated_application_method_not_automatically_collection_error(self):
        # A runtime AttributeError may be a real bug rather than a missing
        # test selector. Do not classify it as test_not_collected without
        # unittest.loader._FailedTest.
        log = (
            "ERROR: test_real_bug (tornado.test.asyncio_test.RealTest)\n"
            "AttributeError: type object 'Backend' has no attribute 'test_missing'\n"
            "Ran 1 test in 0.005s\nFAILED (errors=1)"
        )
        self.assertEqual(classify_test_output(1, log), "test_failure")


if __name__ == "__main__":
    unittest.main()
