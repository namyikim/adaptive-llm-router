"""CPU-only, NO Docker/third-party code execution in unit tests."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.bugsinpy_reproduce import (
    ALLOWED_CASES, REPRODUCED, EXPECTED_COMMITS, EXPECTED_TEST_COMMANDS,
    ReplayError, prepare_metadata, decode_test_commands,
    classify_reproduction, docker_test, run_one,
)


def result(verdict):
    return {"verdict": verdict}


class DockerReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def seed(self, case_id, script):
        project, bug_id = case_id.split("-")
        bugs = self.root / "projects" / project / "bugs" / bug_id
        bugs.mkdir(parents=True)
        (bugs / "run_test.sh").write_text(script, encoding="utf-8")
        buggy_sha, fixed_sha = EXPECTED_COMMITS[case_id]
        info = [
            'python_version="3.6.9"' if project == "tqdm"
            else 'python_version="3.7.0"',
            'buggy_commit_id="' + buggy_sha + '"',
            'fixed_commit_id="' + fixed_sha + '"',
            'test_file="tests/test.py"',
        ]
        (bugs / "bug.info").write_text("\n".join(info), encoding="utf-8")
        proj = self.root / "projects" / project
        (proj / "project.info").write_text(
            'github_url="https://github.com/tqdm/tqdm"' if project == "tqdm"
            else 'github_url="https://github.com/tornadoweb/tornado"'
        )

    def test_actual_reviewed_commands_are_supported(self):
        self.assertEqual(decode_test_commands(
            "python3 -m pytest tqdm/tests/tests_synchronisation.py::test_imap\n"
        ), [["python", "-m", "pytest",
             "tqdm/tests/tests_synchronisation.py::test_imap"]])
        self.assertEqual(len(decode_test_commands(
            "python -m unittest -q tornado.test.asyncio_test.LeakTest.test_ioloop_close_leak\n"
            "python -m unittest -q tornado.test.asyncio_test.LeakTest.test_asyncio_close_leak\n"
        )), 2)

    def test_rejects_arbitrary_scripts_and_shell_features(self):
        malicious = (
            "bash setup.sh", "python setup.py install",
            "python -m pytest ok.py; rm -rf /",
            "python3 -m pytest ok.py && curl https://evil",
            "python -m os system",
            "python -m pytest -k some",
            "python -m unittest -q package.Class.test | tee log",
            "python -m pytest $(touch /tmp/marker)",
        )
        for script in malicious:
            with self.subTest(script=script):
                with self.assertRaises(ReplayError):
                    decode_test_commands(script)

    def test_metadata_dry_run_is_real_and_strict(self):
        self.seed("tqdm-6",
                  "python3 -m pytest tqdm/tests/tests_synchronisation.py::test_imap")
        manifest = prepare_metadata(self.root, "tqdm-6")
        self.assertEqual(manifest["python_version_historical"], "3.6.9")
        self.assertEqual(manifest["docker_image"], "adaptive-bugsinpy:py36")
        self.assertEqual(len(manifest["test_commands"]), 1)
        self.assertEqual(manifest["status"], "not_executed")
        self.assertEqual(manifest["test_commands"], EXPECTED_TEST_COMMANDS["tqdm-6"])
        with self.assertRaises(ValueError):
            prepare_metadata(self.root, "tqdm-99")
        (self.root / "projects/tqdm/project.info").write_text(
            'github_url="https://github.com/attacker/evil"')
        with self.assertRaises(ReplayError):
            prepare_metadata(self.root, "tqdm-6")

    def test_modified_record_is_rejected_even_if_syntax_is_safe(self):
        script = "python3 -m pytest tqdm/tests/tests_synchronisation.py::test_imap"
        self.seed("tqdm-6", script)
        path = self.root / "projects/tqdm/bugs/6/bug.info"
        content = path.read_text()
        path.write_text(content.replace(EXPECTED_COMMITS["tqdm-6"][0], "c" * 40))
        with self.assertRaises(ReplayError):
            prepare_metadata(self.root, "tqdm-6")
        path.write_text(content)
        (path.parent / "run_test.sh").write_text("python3 -m pytest alternate.py")
        with self.assertRaises(ReplayError):
            prepare_metadata(self.root, "tqdm-6")

    def test_reproduction_requires_buggy_failure_and_fixed_pass(self):
        self.assertEqual(classify_reproduction(
            [result("test_failure")], [result("pass")]), REPRODUCED)
        self.assertEqual(classify_reproduction(
            [result("pass")], [result("pass")]), "not_reproduced_both_pass")
        self.assertEqual(classify_reproduction(
            [result("test_failure")], [result("test_failure")]), "inconclusive_tests")
        self.assertEqual(classify_reproduction(
            [result("environment_failure")], [result("pass")]),
            "environment_or_timeout")
        self.assertEqual(classify_reproduction(
            [result("timeout")], [result("pass")]), "environment_or_timeout")
        self.assertEqual(classify_reproduction(
            [result("test_failure")], []), "inconclusive")
        self.assertEqual(classify_reproduction(
            [result("pass"), result("test_failure")],
            [result("pass"), result("pass")]), REPRODUCED)

    def test_docker_command_isolation_flags(self):
        import subprocess
        completed = subprocess.CompletedProcess([], 1, stdout="FAILED test_a\nAssertionError", stderr="")
        with patch("adaptive_llm_router.bugsinpy_reproduce.subprocess.run",
                   return_value=completed) as process:
            outcome = docker_test("adaptive-bugsinpy:py36", self.root,
                                  ["python", "-m", "pytest", "tests/test.py"])
        self.assertEqual(outcome["verdict"], "test_failure")
        args = process.call_args.args[0]
        for required in ("--network=none", "--read-only", "--cap-drop=ALL",
                         "--pids-limit=128", "--memory=2g", "--cpus=2",
                         "--security-opt=no-new-privileges", "--pull=never"):
            self.assertIn(required, args)
        self.assertEqual(args[0:2], ["docker", "run"])
        self.assertEqual(args[-4:], ["python", "-m", "pytest", "tests/test.py"])

    def test_docker_verdict_detects_environment_error(self):
        import subprocess
        completed = subprocess.CompletedProcess([], 1, stdout="", stderr="ModuleNotFoundError: missing")
        with patch("adaptive_llm_router.bugsinpy_reproduce.subprocess.run",
                   return_value=completed):
            result_row = docker_test("adaptive-bugsinpy:py37", self.root,
                                     ["python", "-m", "unittest", "-q", "test.X.y"])
        self.assertEqual(result_row["verdict"], "environment_failure")

    def test_run_one_does_not_invent_success_and_saves_logs(self):
        self.seed("tqdm-6",
                  "python3 -m pytest tqdm/tests/tests_synchronisation.py::test_imap")
        record = prepare_metadata(self.root, "tqdm-6")
        roots = {"buggy": self.root / "buggy", "fixed": self.root / "fixed"}
        for root in roots.values():
            root.mkdir()
        outcomes = iter([
            {"verdict": "test_failure", "output": "AssertionError", "exit_code": 1},
            {"verdict": "pass", "output": "1 passed", "exit_code": 0},
        ])
        with patch("adaptive_llm_router.bugsinpy_reproduce.subprocess.run"), \
             patch("adaptive_llm_router.bugsinpy_reproduce.checkout_versions", return_value=roots), \
             patch("adaptive_llm_router.bugsinpy_reproduce.docker_test",
                   side_effect=lambda *args, **kwargs: next(outcomes)):
            out = run_one(record, self.root, self.root / "out")
        self.assertEqual(out["status"], REPRODUCED)
        self.assertTrue(out["verified_historical_reproduction"])
        self.assertIsNone(out["llm_verified_success"])
        self.assertTrue((self.root / "out/tqdm-6_buggy_1.log").is_file())
        self.assertTrue((self.root / "out/tqdm-6_fixed_1.log").is_file())
        self.assertTrue((self.root / "out/tqdm-6.json").is_file())


if __name__ == "__main__":
    unittest.main()
