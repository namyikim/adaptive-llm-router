"""Deterministic, project-stratified BugsInPy sampling without severity labels.

Samples the frozen public BugsInPy metadata only. No test success is inferred.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

# Select projects with multiple historical bugs and varied Python ecosystems.
# Add projects explicitly before changing the experiment's frozen manifest.
DEFAULT_PROJECTS = (
    "PySnooper", "tqdm", "black", "thefuck", "fastapi", "tornado",
    "youtube-dl", "scrapy", "luigi", "cookiecutter", "httpie", "sanic",
)
DEFAULT_SEED = 20261026


def available_bugs(root: Path, projects: tuple[str, ...] = DEFAULT_PROJECTS) -> dict[str, list[str]]:
    choices = {}
    for name in projects:
        if not name or "/" in name or name in (".", ".."):
            raise ValueError("Invalid project name")
        folder = root / "projects" / name / "bugs"
        if not folder.is_dir():
            continue
        ids = sorted(
            (p.name for p in folder.iterdir()
             if p.is_dir() and p.name.isdigit() and (p / "bug.info").is_file()),
            key=int,
        )
        if ids and (root / "projects" / name / "project.info").is_file():
            choices[name] = ids
    return choices


def stratified_plan(root: Path, *, seed: int = DEFAULT_SEED,
                    projects: tuple[str, ...] = DEFAULT_PROJECTS,
                    max_per_project: int = 20) -> list[tuple[str, str]]:
    """Round-robin shuffled bug IDs: caps oversized repos and avoids ID=1 bias."""
    if max_per_project < 1:
        raise ValueError("max_per_project must be positive")
    options = available_bugs(root, projects=projects)
    if not options:
        raise ValueError("No BugsInPy project metadata found")
    # Deterministic per-project RNG; no dependence on Python's randomized hash.
    pools = {}
    for project, ids in options.items():
        salt = int.from_bytes(
            hashlib.sha256(f"{seed}/{project}".encode()).digest()[:8], "big"
        )
        shuffled = ids.copy()
        random.Random(salt).shuffle(shuffled)
        pools[project] = shuffled[:max_per_project]
    queue = sorted(pools)
    # Keep round-robin fairness even when individual projects have fewer cases.
    result = []
    while any(pools.values()):
        for name in queue:
            if pools[name]:
                result.append((name, pools[name].pop(0)))
    return result


def manifest(root: Path, *, seed: int = DEFAULT_SEED, max_per_project: int = 20,
             projects: tuple[str, ...] = DEFAULT_PROJECTS,
             target_successes: int = 100) -> dict:
    if target_successes < 1:
        raise ValueError("target_successes must be positive")
    plan = stratified_plan(root, seed=seed, projects=projects,
                           max_per_project=max_per_project)
    counts = dict(sorted(Counter(project for project, _ in plan).items()))
    dataset_identity = [
        f"{name}/{bug_id}/{(root / 'projects' / name / 'bugs' / bug_id / 'bug.info').read_text(encoding='utf-8')}"
        for name, bug_id in plan
    ]
    return {
        "source": "BugsInPy",
        "seed": seed,
        "target_successes": target_successes,
        "candidate_count": len(plan),
        "max_per_project": max_per_project,
        "sampled_projects": counts,
        "metadata_sha256": hashlib.sha256(
            "\n".join(dataset_identity).encode("utf-8")
        ).hexdigest(),
        "candidate_ids_in_attempt_order": [f"{name}-{bug_id}" for name, bug_id in plan],
        "note": "Selection is deterministic metadata-only round robin; no stratification by actual bug severity. Plan can yield fewer usable cases than target.",
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset-root", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--target", type=int, default=100)
    p.add_argument("--max-per-project", type=int, default=20)
    args = p.parse_args()
    data = manifest(args.dataset_root, seed=args.seed, target_successes=args.target,
                    max_per_project=args.max_per_project)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Candidates: {data['candidate_count']}; intended successful cases: {data['target_successes']}")


if __name__ == "__main__":
    main()
