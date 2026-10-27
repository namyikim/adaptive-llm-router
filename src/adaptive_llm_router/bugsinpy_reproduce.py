"""Reproduce six BugsInPy *historical tests* in bounded offline Docker containers.

Dry-run is the default. Real execution requires --execute and manually prepared
Docker images. No historical setup.sh or arbitrary shell pipeline is executed.
A buggy-fails/fixed-passes verdict is NOT a model-repair success verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from .bugsinpy_cases import parse_info

ALLOWED_CASES = ("tqdm-6", "tornado-5", "tornado-6", "tornado-7", "tornado-11", "tornado-14")
TORNADO_REMAINING = ("tornado-5", "tornado-7", "tornado-11", "tornado-14")
# Case-specific verifier-only overlays: these files come from pinned FIXED commits.
# Do not expose their content or the implementation patch to model prompts.
REGRESSION_TEST_FILES = {
    "tqdm-6": "tqdm/tests/tests_synchronisation.py",
    "tornado-5": "tornado/test/ioloop_test.py",
    "tornado-6": "tornado/test/asyncio_test.py",
    "tornado-7": "tornado/test/ioloop_test.py",
    "tornado-11": "tornado/test/httpserver_test.py",
    "tornado-14": "tornado/test/ioloop_test.py",
}
# Tornado-7's test existed on both commits, but its body was substantially
# REVISED by the fix. Always compare against the pinned revised verifier test.
REVISED_REGRESSION_TEST_CASES = frozenset({"tornado-7"})
PROJECT_URLS = {"tqdm": "https://github.com/tqdm/tqdm.git",
                "tornado": "https://github.com/tornadoweb/tornado.git"}
IMAGE_NAMES = {"tqdm": "adaptive-bugsinpy:py36",
               "tornado": "adaptive-bugsinpy:py37"}
PYTHON_EXPECTED = {"tqdm": "3.6.9", "tornado": "3.7.0"}

# Frozen six-case subset of BugsInPy master, checked against uploaded source rows.
# Never execute arbitrary test commands or newer commits from a modified dataset.
EXPECTED_COMMITS = {
    "tqdm-6": (
        "a4b9c86db548b2d0dbb5af7a6bbdc26ab47e1eec",
        "6dad2e89019317e875c46d5a3a82a811ad6de2f9",
    ),
    "tornado-5": (
        "2d4053daa56c609d642b214399e046671d4a593e",
        "886643965b5cb782503d8d7b374b7a794ec2077b",
    ),
    "tornado-6": (
        "fb74e4816ccfa7fc6a7abd8c8aab1f415cfc1b13",
        "2905ee4fb3c283d40b10f609359e189c83a0dc06",
    ),
    "tornado-7": (
        "fa3409179588536f2f743d16e537f6f9827fa92f",
        "a3b44cd701e0e82693363701bc0346b0125d2362",
    ),
    "tornado-11": (
        "79ef301eb05cac82c075198e502d94dad296f6aa",
        "1131c9b50a6a4c0868d0d6fa5e0be077cf8fd1ca",
    ),
    "tornado-14": (
        "81ee310adcd905fbdf7c98d9fb6ef0c5a46026c2",
        "1d02ed606f1c52636462633d009bdcbaac644331",
    ),
}
EXPECTED_TEST_COMMANDS = {
    "tqdm-6": [
        ["python", "-m", "pytest", "tqdm/tests/tests_synchronisation.py::test_imap"],
    ],
    "tornado-5": [
        ["python", "-m", "unittest", "-q",
         "tornado.test.ioloop_test.TestPeriodicCallbackMath.test_clock_backwards"],
    ],
    "tornado-6": [
        ["python", "-m", "unittest", "-q",
         "tornado.test.asyncio_test.LeakTest.test_ioloop_close_leak"],
        ["python", "-m", "unittest", "-q",
         "tornado.test.asyncio_test.LeakTest.test_asyncio_close_leak"],
    ],
    "tornado-7": [
        ["python", "-m", "unittest", "-q",
         "tornado.test.ioloop_test.TestIOLoopFutures.test_run_in_executor_native"],
    ],
    "tornado-11": [
        ["python", "-m", "unittest", "-q",
         "tornado.test.httpserver_test.HTTPServerRawTest.test_chunked_request_uppercase"],
    ],
    "tornado-14": [
        ["python", "-m", "unittest", "-q",
         "tornado.test.ioloop_test.TestIOLoopCurrent.test_force_current"],
    ],
}

SHA = re.compile(r"^[0-9a-f]{40}$")
ID = re.compile(r"^(tqdm|tornado)-(?:[0-9]+)$")
# No shell expansions/pipes/redirections. Parse only whitelisted Python test runners.
UNSAFE_SHELL = re.compile(r"[;&|$" + chr(96) + r"<>\\]")
REPRODUCED = "reproduced_buggy_fail_fixed_pass"


class ReplayError(RuntimeError):
    pass


def decode_test_commands(script: str) -> list[list[str]]:
    """Only 'python[3] -m pytest ...' or 'python[3] -m unittest ...'."""
    commands = []
    for raw in script.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if UNSAFE_SHELL.search(line):
            raise ReplayError("Unsafe shell syntax in BugsInPy run_test.sh")
        try:
            cmd = shlex.split(line)
        except ValueError as exc:
            raise ReplayError("Invalid quoting in test command") from exc
        if len(cmd) not in range(4, 9) or cmd[:2] not in (
            ["python", "-m"], ["python3", "-m"]
        ):
            raise ReplayError("Non-whitelisted Python test invocation")
        if cmd[2] not in ("pytest", "unittest"):
            raise ReplayError("Only python -m pytest/unittest accepted")
        args = cmd[3:]
        if cmd[2] == "pytest":
            # Option-less explicit pytest node targets only.
            if not all(re.fullmatch(r"[A-Za-z0-9_./:-]+", a)
                       and a.endswith(".py") or "::" in a
                       for a in args):
                raise ReplayError("Unsupported pytest node selector")
        else:
            if args[0] != "-q" or len(args) != 2 or not re.fullmatch(
                r"[A-Za-z0-9_.]+", args[1]
            ):
                raise ReplayError("Only explicit unittest -q dotted method accepted")
        # Normalize executable to the container's Python, not the host.
        commands.append(["python", *cmd[1:]])
    if not commands or len(commands) > 4:
        raise ReplayError("Expected 1 to 4 explicit tests")
    return commands


def prepare_metadata(dataset_root: Path, case_id: str) -> dict:
    if case_id not in ALLOWED_CASES:
        raise ValueError("Only six preapproved divergence cases are supported")
    project, number = case_id.split("-", 1)
    folder = dataset_root / "projects" / project / "bugs" / number
    info = parse_info(folder / "bug.info")
    pinfo = parse_info(dataset_root / "projects" / project / "project.info")
    repo_url = pinfo.get("github_url", "").removesuffix(".git")
    if repo_url != PROJECT_URLS[project].removesuffix(".git"):
        raise ReplayError("Unexpected upstream repository for selected case")
    if info.get("python_version") != PYTHON_EXPECTED[project]:
        raise ReplayError("Unreviewed historical Python version")
    buggy, fixed = info.get("buggy_commit_id"), info.get("fixed_commit_id")
    if not isinstance(buggy, str) or not isinstance(fixed, str) or not SHA.fullmatch(buggy) or not SHA.fullmatch(fixed):
        raise ReplayError("Invalid BugsInPy commit metadata")
    script = folder / "run_test.sh"
    if not script.is_file():
        raise ReplayError("BugsInPy run_test.sh missing")
    commands = decode_test_commands(script.read_text(encoding="utf-8"))
    if (buggy, fixed) != EXPECTED_COMMITS[case_id]:
        raise ReplayError("BugsInPy SHA metadata differs from reviewed six-case manifest")
    if commands != EXPECTED_TEST_COMMANDS[case_id]:
        raise ReplayError("BugsInPy test commands differ from reviewed six-case manifest")
    return {
        "case_id": case_id, "project": project, "source": "BugsInPy",
        "python_version_historical": info["python_version"],
        "docker_image": IMAGE_NAMES[project],
        "repository": PROJECT_URLS[project],
        "buggy_commit": buggy, "fixed_commit_for_verifier_only": fixed,
        "related_test_file": info.get("test_file"),
        "test_commands": commands,
        "status": "not_executed",
        "confidence_note": "Known test selector from BugsInPy; no LLM repair or independent difficulty label",
    }


def _git(args: list[str], *, cwd: Path | None = None, timeout: int = 360) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True,
                   timeout=timeout, text=True)


def checkout_versions(record: dict, workspace: Path) -> dict[str, Path]:
    """Download historical public repos; no third-party setup.sh is executed."""
    project, case_id = record["project"], record["case_id"]
    repo_root = workspace / "repos" / project
    if not (repo_root / ".git").is_dir():
        repo_root.parent.mkdir(parents=True, exist_ok=True)
        _git(["clone", "--filter=blob:none", "--no-checkout", "--quiet",
              record["repository"], str(repo_root)], timeout=900)
    roots = {}
    for version, key in (("buggy", "buggy_commit"),
                         ("fixed", "fixed_commit_for_verifier_only")):
        target = (workspace / "checkouts" / case_id / version).resolve()
        if not (target / ".git").exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            _git(["worktree", "add", "--detach", str(target), record[key]],
                 cwd=repo_root, timeout=480)
        # Guard any stale reused worktree: verify exact commit.
        actual = subprocess.check_output(
            ["git", "-C", str(target), "rev-parse", "HEAD"], text=True
        ).strip()
        if actual != record[key]:
            raise ReplayError("Historical worktree is at the wrong commit")
        roots[version] = target
    return roots


def classify_test_output(exit_code: int, output: str) -> str:
    """Classify test outcomes, not words in printed snippets of test source.

    In tqdm-6, except ImportError: appeared in a traceback's code
    excerpt although the actual failure was AttributeError: ...total.
    Broad substring matching incorrectly hid the confirmed regression.
    """
    if exit_code == 0:
        return "pass"
    # unittest synthesizes a _FailedTest when a requested class/method does
    # not exist. The body of the test never ran: NOT a historical failure.
    if (re.search(r"^ERROR:\s+[^\n]+\(unittest\.loader\._FailedTest\)", output, re.M)
            and re.search(
                r"^AttributeError:\s+module\s+['\"][^'\"]+['\"]"
                r"\s+has no attribute\s+['\"][^'\"]+['\"]",
                output, re.M,
            )):
        return "test_not_collected"
    if re.search(
        r"(?:^ERROR:\s*not found:|^collected 0 items\b|^no tests ran\b)",
        output, re.I | re.M,
    ):
        return "test_not_collected"
    environment_error = (
        r"^\s*(?:E\s+)?(?:ModuleNotFoundError|ImportError|SyntaxError):"
        r"|^ERROR collecting\b"
        r"|^INTERNALERROR\b"
        r"|^ERROR:\s*(?:usage|unrecognized arguments|unknown option)\b"
        r"|^FAILED\s+\S+.*-\s*(?:ModuleNotFoundError|ImportError|SyntaxError):"
    )
    if re.search(environment_error, output, re.M):
        return "environment_failure"
    if re.search(
        r"^FAILED\s+\S+|^FAIL:\s+|^E\s+(?:assert\b|AssertionError:|AttributeError:)"
        r"|^FAILED\s+\(failures=[1-9]",
        output, re.M,
    ):
        return "test_failure"
    return "nonzero_unclassified"


def docker_test(image: str, source_root: Path, command: list[str],
                *, timeout_seconds: int = 120,
                regression_test_from_fixed: Path | None = None) -> dict:
    """Run one allowlisted test; optionally bind-mount a fixed-commit TEST file.

    Does not copy implementation patches. Fixed-commit verifier test files
    are only used for the six SHA-pinned and reviewed historical cases.
    """
    args = [
        "docker", "run", "--rm", "--pull=never",
        "--network=none", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--pids-limit=128",
        "--memory=2g", "--cpus=2", "--user=65534:65534",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m",
        "--mount", f"type=bind,src={source_root},dst=/src,readonly",
        "--workdir", "/src", "--env", "HOME=/tmp",
        "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--env", "PYTHONPATH=/src:/src/tqdm:/src/tqdm/tests",
    ]
    if regression_test_from_fixed is not None:
        allowed_test_files = {
            "tests_synchronisation.py": "tqdm/tests/tests_synchronisation.py",
            "asyncio_test.py": "tornado/test/asyncio_test.py",
            "ioloop_test.py": "tornado/test/ioloop_test.py",
            "httpserver_test.py": "tornado/test/httpserver_test.py",
        }
        relative_test_file = allowed_test_files.get(regression_test_from_fixed.name)
        if (not regression_test_from_fixed.is_file() or relative_test_file is None
                or not str(regression_test_from_fixed.resolve()).endswith(
                    "/" + relative_test_file)):
            raise ReplayError("Refusing unreviewed regression test overlay")
        args += [
            "--mount",
            f"type=bind,src={regression_test_from_fixed.resolve()},"
            f"dst=/src/{relative_test_file},readonly",
        ]
    args += [image, *command]
    started = time.monotonic()
    try:
        res = subprocess.run(args, capture_output=True, text=True,
                             timeout=timeout_seconds, check=False)
        output = (res.stdout or "") + "\n" + (res.stderr or "")
        verdict = classify_test_output(res.returncode, output)
        return {
            "command": command, "exit_code": res.returncode, "verdict": verdict,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": output[-18000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command, "exit_code": None, "verdict": "timeout",
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": str(exc)[-2000:],
        }
    except OSError as exc:
        return {
            "command": command, "exit_code": None, "verdict": "environment_failure",
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": type(exc).__name__,
        }


def classify_reproduction(buggy: list[dict], fixed: list[dict]) -> str:
    """Passing fixed tests alone is insufficient: require a real buggy test failure."""
    if not buggy or len(buggy) != len(fixed):
        return "inconclusive"
    all_results = buggy + fixed
    if any(row["verdict"] in ("environment_failure", "timeout",
                                  "nonzero_unclassified", "test_not_collected")
           for row in all_results):
        return "environment_or_timeout"
    if all(row["verdict"] == "pass" for row in fixed) and any(
        row["verdict"] == "test_failure" for row in buggy
    ):
        return REPRODUCED
    if all(row["verdict"] == "pass" for row in buggy + fixed):
        return "not_reproduced_both_pass"
    return "inconclusive_tests"


def run_one(record: dict, workspace: Path, output_root: Path) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    case_id = record["case_id"]
    result = {**record, "status": "environment_unavailable",
              "llm_patch_attempted": False, "llm_verified_success": None}
    output_path = output_root / (case_id + ".json")
    # Preserve a minimal status on failure rather than claim an empty success.
    try:
        subprocess.run(["docker", "image", "inspect", record["docker_image"]],
                       capture_output=True, check=True, timeout=30)
        sources = checkout_versions(record, workspace)
        verdicts = {}
        for version in ("buggy", "fixed"):
            rows = []
            for i, command in enumerate(record["test_commands"]):
                row = docker_test(record["docker_image"], sources[version], command)
                verifier_test_file = REGRESSION_TEST_FILES.get(case_id)
                test_revised_in_fixed = case_id in REVISED_REGRESSION_TEST_CASES
                need_verifier_test = (
                    version == "buggy" and verifier_test_file is not None
                    and (row["verdict"] == "test_not_collected"
                         or test_revised_in_fixed)
                )
                if need_verifier_test:
                    # For missing tests, mount only the pinned fixed commit's
                    # TEST file. Tornado-7 existed before the fix, but the
                    # fixed commit substantially REVISED the test; preserve
                    # the original result before verifying against that test.
                    original_suffix = ("revised_test_original" if test_revised_in_fixed
                                       else "missing_test")
                    original_log = f"{case_id}_buggy_{i + 1}_{original_suffix}.log"
                    (output_root / original_log).write_text(
                        row.pop("output"), encoding="utf-8")
                    test_from_fixed = sources["fixed"] / verifier_test_file
                    backport = result.setdefault("regression_test_backport", {
                        "provenance": "historical_fixed_commit_test_file_for_verifier_only",
                        "no_implementation_patch_copied": True,
                        "fixed_test_file": verifier_test_file,
                        "original_test_log": original_log,
                        "missing_test_log": (
                            original_log if not test_revised_in_fixed else None
                        ),
                        "test_sha256": (
                            hashlib.sha256(test_from_fixed.read_bytes()).hexdigest()
                            if test_from_fixed.is_file() else None
                        ),
                        "attempts": [],
                    })
                    backport["attempts"].append({
                        "test_command_index": i + 1,
                        "original_verdict": row["verdict"],
                        "original_test_log": original_log,
                        "test_overlay_reason": (
                            "fixed_commit_revised_test" if test_revised_in_fixed
                            else "missing_regression_test_in_buggy_commit"
                        ),
                    })
                    if test_from_fixed.is_file():
                        row = docker_test(
                            record["docker_image"], sources[version], command,
                            regression_test_from_fixed=test_from_fixed)
                        row["test_origin"] = "fixed_commit_regression_test_only"
                    else:
                        row = {
                            "command": command,
                            "exit_code": None,
                            "verdict": "test_not_collected",
                            "output": "Pinned verifier-only regression test file is missing",
                        }
                row["output_file"] = f"{case_id}_{version}_{i + 1}.log"
                (output_root / row["output_file"]).write_text(
                    row.pop("output"), encoding="utf-8")
                rows.append(row)
            verdicts[version] = rows
        result["tests"] = verdicts
        result["status"] = classify_reproduction(verdicts["buggy"], verdicts["fixed"])
        result["verified_historical_reproduction"] = result["status"] == REPRODUCED
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ReplayError) as exc:
        result["error_type"] = type(exc).__name__
        result["status"] = "environment_unavailable"
        result["verified_historical_reproduction"] = False
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset-root", type=Path, required=True)
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--output-root", type=Path, required=True)
    p.add_argument("--cases", nargs="+",
                   choices=(*ALLOWED_CASES, "all", "tornado-remaining"),
                   default=["tqdm-6", "tornado-6"])
    p.add_argument("--execute", action="store_true",
                   help="Explicit opt-in to cloning and running public historical tests in Docker")
    args = p.parse_args()
    groups = {"all": ALLOWED_CASES, "tornado-remaining": TORNADO_REMAINING}
    if any(group in args.cases for group in groups) and len(args.cases) != 1:
        p.error("Case groups must be selected alone")
    cases = list(groups.get(args.cases[0], args.cases)) if len(args.cases) == 1 else args.cases
    args.output_root.mkdir(parents=True, exist_ok=True)
    manifest = []
    for case_id in dict.fromkeys(cases):
        item = prepare_metadata(args.dataset_root, case_id)
        result = run_one(item, args.workspace, args.output_root) if args.execute else item
        manifest.append(result)
        print(case_id, "->", result["status"])
    report = {
        "kind": "historical_buggy_vs_fixed_test_replay",
        "executed": bool(args.execute), "n_cases": len(manifest),
        "verified_reproductions": sum(r.get("verified_historical_reproduction") is True
                                      for r in manifest),
        "cases": [{"id": r["case_id"], "status": r["status"]}
                  for r in manifest],
        "note": "Real bug reproduction tests ONLY; not LLM repair success or routing quality.",
    }
    (args.output_root / "reproduction_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.execute:
        (args.output_root / "reproduction_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
