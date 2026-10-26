"""Offline tests for real-history BugsInPy extraction and paired Kev analysis."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.bugsinpy_cases import (
    DEFAULT_BUGS, CasePreparationError, clone_project, collect_cases, make_case,
    parse_info,
)
from adaptive_llm_router.bugsinpy_compare import (
    collect_decisions, compare_decisions, read_cases, read_rows,
)


def run_git(root, *argv):
    return subprocess.run(["git", *argv], cwd=root, text=True, capture_output=True,
                          check=True).stdout.strip()


class BugsInPyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        repo = self.root / "upstream"
        repo.mkdir()
        run_git(repo, "init", "-q")
        run_git(repo, "config", "user.name", "Test")
        run_git(repo, "config", "user.email", "test@example.com")
        (repo / "module.py").write_text("def get(x):\n    return x[0]\n")
        (repo / "test_module.py").write_text("from module import get\nassert get([1]) == 1\n")
        run_git(repo, "add", ".")
        run_git(repo, "commit", "-qm", "buggy")
        self.bug_sha = run_git(repo, "rev-parse", "HEAD")
        (repo / "module.py").write_text("def get(x):\n    return x[0] if x else None\n")
        run_git(repo, "add", ".")
        run_git(repo, "commit", "-qm", "fix")
        self.fixed_sha = run_git(repo, "rev-parse", "HEAD")
        self.dataset = self.root / "dataset"
        b = self.dataset / "projects" / "demo" / "bugs" / "1"
        b.mkdir(parents=True)
        (b / "bug.info").write_text(
            f'python_version="3.8.1"\nbuggy_commit_id="{self.bug_sha}"\n'
            f'fixed_commit_id="{self.fixed_sha}"\ntest_file="test_module.py"\n')
        (b.parents[1] / "project.info").write_text('github_url="https://github.com/demo/repo"\n')
        self.repo = repo

    def test_info_parser(self):
        info = parse_info(self.dataset / "projects" / "demo" / "bugs" / "1" / "bug.info")
        self.assertEqual(info["buggy_commit_id"], self.bug_sha)
        self.assertEqual(info["python_version"], "3.8.1")

    def test_case_from_real_buggy_git_commit(self):
        with patch("adaptive_llm_router.bugsinpy_cases.clone_project", return_value=self.repo):
            row = make_case(self.dataset, self.root / "checkouts", "demo", "1")
        self.assertIn("return x[0]", row["input"])
        self.assertNotIn("if x else None", row["input"])
        self.assertEqual(row["log_status"], "not_reproduced")
        self.assertFalse(row["verification"]["executed"])
        self.assertIn("fixing diff", row["oracle_hint_warning"])
        self.assertEqual(row["selected_files"], ["module.py"])

    def test_test_only_mode_never_reads_fix_diff_or_fixed_source(self):
        with patch("adaptive_llm_router.bugsinpy_cases.clone_project", return_value=self.repo):
            with patch("adaptive_llm_router.bugsinpy_cases.git",
                       wraps=__import__("adaptive_llm_router.bugsinpy_cases",
                                        fromlist=["git"]).git) as mocked:
                row = make_case(self.dataset, self.root / "checkouts", "demo", "1",
                                context_mode="test_only")
        self.assertEqual(row["context_mode"], "test_only")
        self.assertIn("test_module.py", row["input"])
        self.assertNotIn("return x[0] if x else None", row["input"])
        self.assertEqual(row["selected_files"], ["test_module.py"])
        self.assertFalse(any(args[0][0][0] == "diff" for args in mocked.call_args_list))

    def test_target_successes_stops_early_and_preserves_failure_report(self):
        output = self.root / "cases.jsonl"
        failure_log = self.root / "collection_errors.jsonl"
        selection = (("demo", "999"), ("demo", "1"), ("demo", "1"))
        with patch("adaptive_llm_router.bugsinpy_cases.clone_project", return_value=self.repo):
            result = collect_cases(
                self.dataset, self.root, output, selection=selection,
                context_mode="test_only", target_successes=2, failure_log=failure_log,
            )
        self.assertEqual(result["cases_written"], 1)
        self.assertEqual(result["shortfall"], 1)
        self.assertEqual(result["context_mode"], "test_only")
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(len(failure_log.read_text().splitlines()), 1)
        with self.assertRaises(ValueError):
            collect_cases(self.dataset, self.root, output, selection=selection,
                          context_mode="fix_diff")

    def test_success_target_does_not_overshoot(self):
        out = self.root / "cases.jsonl"
        with patch("adaptive_llm_router.bugsinpy_cases.clone_project", return_value=self.repo):
            res = collect_cases(self.dataset, self.root, out,
                                selection=(("demo", "1"), ("demo", "2")),
                                context_mode="test_only", target_successes=1)
        self.assertEqual(res["cases_written"], 1)
        self.assertEqual(res["attempts_this_run"], 1)

    def test_attached_real_log_is_explicitly_labeled(self):
        logs = self.root / "logs"
        logs.mkdir()
        (logs / "demo-1.log").write_text("Traceback: IndexError: list index out of range")
        with patch("adaptive_llm_router.bugsinpy_cases.clone_project", return_value=self.repo):
            row = make_case(self.dataset, self.root / "checkouts", "demo", "1", logs_dir=logs)
        self.assertIn("IndexError", row["input"])
        self.assertEqual(row["task_type"], "log")
        self.assertEqual(row["log_status"], "externally_supplied")

    def test_collection_incremental_resume_without_duplicates(self):
        output = self.root / "results" / "cases.jsonl"
        with patch("adaptive_llm_router.bugsinpy_cases.clone_project", return_value=self.repo):
            first = collect_cases(self.dataset, self.root, output, selection=(("demo", "1"),))
            second = collect_cases(self.dataset, self.root, output, selection=(("demo", "1"),))
        self.assertEqual(first["cases_written"], 1)
        self.assertEqual(second["cases_written"], 1)
        self.assertEqual(len(read_cases(output)), 1)

    def test_reject_untrusted_repo_urls(self):
        with self.assertRaises(CasePreparationError):
            clone_project("file:///etc/passwd", self.root / "dest")
        with self.assertRaises(CasePreparationError):
            clone_project("https://github.com/a/b?token=secret", self.root / "dest")
        with self.assertRaises(ValueError):
            make_case(self.dataset, self.root, "../traversal", "1")

    def test_paired_results_are_never_claimed_as_accuracy(self):
        with patch("adaptive_llm_router.bugsinpy_cases.clone_project", return_value=self.repo):
            case = make_case(self.dataset, self.root, "demo", "1")
        inp = self.root / "cases.jsonl"
        inp.write_text(json.dumps(case) + "\n")
        out = self.root / "decisions.jsonl"
        def mock_selector(task_type, content, **kwargs):
            return SimpleNamespace(as_dict=lambda: {
                "status": "proposed",
                "tier": "l2",
                "proposed_tier": "l2",
                "p_max": 0.75,
                "decision_latency_ms": 20.5,
            })
        with patch("adaptive_llm_router.bugsinpy_compare.select_analysis_model",
                   side_effect=mock_selector) as mocked:
            for label in ("kev-9b@v1.0", "kev-4b@v1.0"):
                collect_decisions(inp, out, label)
                collect_decisions(inp, out, label)
        self.assertEqual(mocked.call_count, 2)  # resume/skip already-saved rows
        report = compare_decisions(read_cases(inp), read_rows(out))
        self.assertEqual(report["n_paired"], 1)
        self.assertEqual(report["raw_agreement_rate"], 1.0)
        self.assertNotIn("accuracy", report)
        self.assertIn("oracle", report["warnings"][1])

    def test_no_pair_when_input_fingerprint_mismatched(self):
        case = {"id": "one", "source": "BugsInPy", "task_type": "code",
                "input": "real code", "input_sha256": "expected"}
        row = {"id": "one", "model_label": "kev-9b@v1.0", "input_sha256": "other",
               "status": "proposed", "decision": {"tier": "l1"}}
        report = compare_decisions([case], [row])
        self.assertEqual(report["n_paired"], 0)
        self.assertIsNone(report["raw_agreement_rate"])

    def test_failures_are_not_fabricated_l3_success(self):
        case = {"id": "one", "source": "BugsInPy", "task_type": "code",
                "input": "buggy example", "input_sha256": "somehash"}
        inp = self.root / "cases.jsonl"
        inp.write_text(json.dumps(case) + "\n")
        out = self.root / "decisions.jsonl"
        with patch("adaptive_llm_router.bugsinpy_compare.select_analysis_model",
                   side_effect=RuntimeError("server down")):
            collect_decisions(inp, out, "kev-9b@v1.0")
        saved = read_rows(out)
        self.assertEqual(saved[0]["status"], "failed")
        self.assertIsNone(saved[0]["decision"])
        report = compare_decisions([case], saved)
        self.assertEqual(report["models"]["kev-9b@v1.0"]["n_failed_decisions"], 1)


if __name__ == "__main__":
    unittest.main()
