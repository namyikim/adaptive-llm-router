"""Reproduce six BugsInPy *historical tests* in bounded offline Docker containers.

Dry-run is the default. Real execution requires --execute and manually prepared
Docker images. No historical setup.sh or arbitrary shell pipeline is executed.
A buggy-fails/fixed-passes verdict is NOT a model-repair success verdict.
"""
from __future__ import annotations

import argparse
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
PROJECT_URLS = {"tqdm": "https://github.com/tqdm/tqdm.git",
                "tornado": "https://github.com/tornadoweb/tornado.git"}
IMAGE_NAMES = {"tqdm": "adaptive-bugsinpy:py36",
               "tornado": "adaptive-bugsinpy:py37"}
PYTHON_EXPECTED = {"tqdm": "3.6.9", "tornado": "3.7.0"}
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


def docker_test(image: str, source_root: Path, command: list[str],
                *, timeout_seconds: int = 120) -> dict:
    """Run one allowlisted test without network, privileges or writable sources."""
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
        image, *command,
    ]
    started = time.monotonic()
    try:
        res = subprocess.run(args, capture_output=True, text=True,
                             timeout=timeout_seconds, check=False)
        output = (res.stdout or "") + "\n" + (res.stderr or "")
        if res.returncode == 0:
            verdict = "pass"
        elif re.search(r"(ModuleNotFoundError|ImportError|No module named|SyntaxError|INTERNALERROR|unknown option)", output):
            verdict = "environment_failure"
        elif re.search(r"(AssertionError|FAILED|FAIL:|E\s+assert|(?:[1-9]\d* )?failed(?:,| in|$))",
                       output, re.M):
            verdict = "test_failure"
        else:
            verdict = "nonzero_unclassified"
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
    if any(row["verdict"] in ("environment_failure", "timeout", "nonzero_unclassified")
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
                row["output_file"] = f"{case_id}_{version}_{i + 1}.log"
                (output_root / row["output_file"]).write_text(row.pop("output"), encoding="utf-8")
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
    p.add_argument("--cases", nargs="+", choices=(*ALLOWED_CASES, "all"),
                   default=["tqdm-6", "tornado-6"])
    p.add_argument("--execute", action="store_true",
                   help="Explicit opt-in to cloning and running public historical tests in Docker")
    args = p.parse_args()
    cases = list(ALLOWED_CASES) if args.cases == ["all"] else args.cases
    if "all" in cases and args.cases != ["all"]:
        p.error("--cases all must be used alone")
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
