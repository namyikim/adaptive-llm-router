"""Build code-routing examples from actual BugsInPy buggy commits.

No third-party tests are executed, no patches are supplied to the router and
NO FAILURE LOG IS CLAIMED. A log is included only if the user explicitly
supplies independently captured reproduction output. Selection of files by
bug-fixing diff is an oracle hint, so examples are for exploratory comparison,
NOT unbiased routing-quality evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

DEFAULT_BUGS = (("PySnooper", "1"), ("PySnooper", "2"), ("PySnooper", "3"),
                ("tqdm", "1"), ("tqdm", "2"), ("tqdm", "3"))
ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,50}$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class CasePreparationError(RuntimeError):
    pass


def parse_info(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise CasePreparationError(f"Missing BugsInPy metadata: {path}")
    fields = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        fields[key] = value
    return fields


def git(args: list[str], *, cwd: Path | None = None, timeout: int = 240) -> str:
    try:
        p = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True,
                           timeout=timeout, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise CasePreparationError(f"Git operation failed: {args[0]}") from exc
    return p.stdout


def clone_project(github_url: str, directory: Path) -> Path:
    parsed = urlparse(github_url)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise CasePreparationError("BugsInPy project URL must use public HTTPS github.com")
    if not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?/?", parsed.path):
        raise CasePreparationError("Unexpected BugsInPy GitHub path")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise CasePreparationError("Unexpected URL parameter")
    if not (directory / ".git").is_dir():
        directory.parent.mkdir(parents=True, exist_ok=True)
        # Whole history required because buggy/fixed historical commits are not at HEAD.
        git(["clone", "--filter=blob:none", "--no-checkout", "--quiet",
             github_url, str(directory)], timeout=480)
    return directory


def make_case(dataset_root: Path, checkout_root: Path, project: str, bug_id: str,
              *, max_code_chars: int = 4300, max_test_chars: int = 1200,
              logs_dir: Path | None = None,
              context_mode: str = "fix_diff") -> dict:
    if context_mode not in ("fix_diff", "test_only"):
        raise ValueError("context_mode must be fix_diff or test_only")
    if not ID_PATTERN.fullmatch(project) or not bug_id.isdigit():
        raise ValueError("Invalid project or bug ID")
    bug_dir = dataset_root / "projects" / project / "bugs" / bug_id
    metadata = parse_info(bug_dir / "bug.info")
    project_info = parse_info(dataset_root / "projects" / project / "project.info")
    sha = metadata.get("buggy_commit_id", "")
    fixed_sha = metadata.get("fixed_commit_id", "")
    if not SHA_PATTERN.fullmatch(sha) or not SHA_PATTERN.fullmatch(fixed_sha):
        raise CasePreparationError("Bug record has invalid commit SHAs")
    url = project_info.get("github_url", "")
    repo = clone_project(url, checkout_root / project)
    test_file = metadata.get("test_file", "").split(";")[0].strip()
    test_excerpt = ""
    if test_file.endswith(".py") and not test_file.startswith("/") and ".." not in Path(test_file).parts:
        try:
            test_excerpt = git(["show", f"{sha}:{test_file}"], cwd=repo, timeout=120)[:max_test_chars]
        except CasePreparationError:
            pass
    snippets = []
    paths = []
    if context_mode == "test_only":
        # Avoid leaking fix-diff file paths. This is still a KNOWN test locator
        # from BugsInPy metadata, not a bug report or a reproduced stack trace.
        if not test_excerpt.strip():
            raise CasePreparationError("Cannot inspect test at buggy commit in test_only mode")
        paths = [test_file]
    else:
        # Historical mode for backward comparison: this is a file-location oracle.
        raw_paths = git(["diff", "--name-only", sha, fixed_sha, "--", "*.py"], cwd=repo)
        paths = [path for path in raw_paths.splitlines()
                 if path.endswith(".py") and not path.startswith("/")
                 and ".." not in Path(path).parts]
        if not paths:
            raise CasePreparationError("No Python source changes in these two commits")
        remaining = max_code_chars
        for path in paths[:3]:
            if remaining <= 50:
                break
            try:
                code = git(["show", f"{sha}:{path}"], cwd=repo, timeout=120)
            except CasePreparationError:
                continue
            excerpt = code[:min(remaining, 2100)]
            snippets.append(f"Buggy source: {path}\n{excerpt}")
            remaining -= len(excerpt)
        if not snippets:
            raise CasePreparationError("No source file exists at buggy commit")
    case_id = f"{project}-{bug_id}"
    captured_log = None
    if logs_dir is not None:
        candidate = logs_dir / f"{case_id}.log"
        if candidate.is_file():
            captured_log = candidate.read_text(encoding="utf-8", errors="replace")[:2500]
    if context_mode == "test_only":
        evidence = (
            "Triage this historical Python project's test context; no exception "
            "traceback or executed failure result is available. Select the minimum "
            "LLM tier to investigate likely causes and decide what additional "
            f"evidence is needed. Project: {project}. "
            f"Historical Python: {metadata.get('python_version', 'unknown')}.\n"
            f"Known affected test path from dataset metadata: {test_file}.\n"
            f"Test code excerpt from buggy commit:\n{test_excerpt}"
        )
    else:
        evidence = (
            "Analyze a real historical Python bug. Diagnose likely failure causes "
            f"and select the minimum LLM tier for analysis. Project: {project}. "
            f"Python version at historical bug: {metadata.get('python_version', 'unknown')}.\n"
            f"Related test path: {test_file or 'not specified'}.\n"
            + "\n\n".join(snippets)
        )
        if test_excerpt:
            evidence += f"\n\nTest source excerpt:\n{test_excerpt}"
    if captured_log:
        evidence += f"\n\nExternally supplied test failure log:\n{captured_log}"
    case = {
        "id": case_id,
        "task_type": "log" if captured_log else "code",
        "source": "BugsInPy",
        "github_url": url,
        "buggy_commit_id": sha,
        "fixed_commit_id_for_verifier_only": fixed_sha,
        "test_file": test_file,
        "selected_files": paths[:3],
        "context_mode": context_mode,
        "context_selection": ("known_test_from_metadata" if context_mode == "test_only"
                              else "fixing_diff_filename_oracle"),
        "log_status": "externally_supplied" if captured_log else "not_reproduced",
        "input": evidence,
        "input_sha256": hashlib.sha256(evidence.encode()).hexdigest(),
        "verification": {
            "executed": False,
            "independent_outcome": None,
            "note": "No tests were run; no true bug-fix success or severity labels.",
        },
        "oracle_hint_warning": ("Known test path from BugsInPy metadata; no fix diff used. "
                                "Missing reproduced failure and unseen source context."
                                if context_mode == "test_only" else
                                "Source files preselected using fixing diff paths; not a blind benchmark."),
    }
    return case


def collect_cases(dataset_root: Path, checkout_root: Path, output: Path,
                  selection: tuple[tuple[str, str], ...] = DEFAULT_BUGS,
                  logs_dir: Path | None = None,
                  checkpoint_callback: Callable[[], None] | None = None,
                  context_mode: str = "fix_diff",
                  target_successes: int | None = None,
                  failure_log: Path | None = None) -> dict:
    if target_successes is not None and target_successes < 1:
        raise ValueError("target_successes must be positive")
    if context_mode not in ("fix_diff", "test_only"):
        raise ValueError("Invalid context mode")
    output.parent.mkdir(parents=True, exist_ok=True)
    if failure_log is not None:
        failure_log.parent.mkdir(parents=True, exist_ok=True)
    done, errors = [], []
    # Resume safely; each finished record is flushed to disk immediately.
    if output.exists():
        for line in output.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.append(json.loads(line))
    if any(row.get("context_mode", "fix_diff") != context_mode for row in done):
        raise ValueError("Cannot resume using a different context_mode in same cases file")
    prior_ids = {row["id"] for row in done}
    attempted = 0
    for project, bug_id in selection:
        if target_successes is not None and len(done) >= target_successes:
            break
        if f"{project}-{bug_id}" in prior_ids:
            continue
        attempted += 1
        try:
            row = make_case(dataset_root, checkout_root, project, bug_id,
                            logs_dir=logs_dir, context_mode=context_mode)
            with output.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
                import os
                os.fsync(stream.fileno())
            done.append(row)
        except (CasePreparationError, OSError, ValueError) as exc:
            failure = {"id": f"{project}-{bug_id}", "error": str(exc),
                       "error_type": type(exc).__name__}
            errors.append(failure)
            if failure_log is not None:
                with failure_log.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(failure, ensure_ascii=False) + "\n")
                    stream.flush()
                    import os
                    os.fsync(stream.fileno())
                if checkpoint_callback:
                    checkpoint_callback()
            continue
        # Fail closed if Drive API upload fails: never treat a local-only case as saved.
        if checkpoint_callback:
            checkpoint_callback()
    return {"cases_written": len(done), "target_successes": target_successes,
            "shortfall": (max(0, target_successes - len(done)) if target_successes else None),
            "attempts_this_run": attempted, "context_mode": context_mode,
            "errors": errors, "output": str(output),
            "note": "Historical test/source context, not reproduced failing logs or verified task quality."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset-root", type=Path, required=True)
    p.add_argument("--checkout-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--logs-dir", type=Path, default=None)
    args = p.parse_args()
    result = collect_cases(args.dataset_root, args.checkout_root, args.output, logs_dir=args.logs_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["cases_written"]:
        raise SystemExit("No usable BugsInPy cases were collected")


if __name__ == "__main__":
    main()
