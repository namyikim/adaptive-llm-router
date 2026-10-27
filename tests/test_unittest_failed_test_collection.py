"""Prevent false bug-reproduction claims from unittest failed test discovery."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.bugsinpy_reproduce import (
    classify_test_output, classify_reproduction,
)

TORNADO_REAL_LOG = """
======================================================================
ERROR: LeakTest (unittest.loader._FailedTest)
----------------------------------------------------------------------
AttributeError: module 'tornado.test.asyncio_test' has no attribute 'LeakTest'

----------------------------------------------------------------------
Ran 1 test in 0.000s

FAILED (errors=1)
"""


class FailedTestCollectionTests(unittest.TestCase):
    def test_tornado_6_actual_loader_failure_is_not_bug_reproduction(self):
        self.assertEqual(classify_test_output(1, TORNADO_REAL_LOG), "test_not_collected")
        fixed = [{"verdict": "pass"}, {"verdict": "pass"}]
        buggy = [{"verdict": classify_test_output(1, TORNADO_REAL_LOG)}] * 2
        self.assertEqual(classify_reproduction(buggy, fixed), "environment_or_timeout")

    def test_real_unittest_method_failure_still_detected(self):
        failure = """
======================================================================
FAIL: test_foo (package.tests.TestFoo)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/src/package/tests.py", line 12, in test_foo
    self.assertEqual(1, 2)
AssertionError: 1 != 2

----------------------------------------------------------------------
Ran 1 test in 0.020s

FAILED (failures=1)
"""
        self.assertEqual(classify_test_output(1, failure), "test_failure")

    def test_unittest_environment_failure_still_not_bug(self):
        output = """
======================================================================
ERROR: test_foo (unittest.loader._FailedTest)
----------------------------------------------------------------------
ModuleNotFoundError: No module named 'some_dependency'

Ran 1 test in 0.000s
FAILED (errors=1)
"""
        self.assertEqual(classify_test_output(1, output), "environment_failure")


if __name__ == "__main__":
    unittest.main()
