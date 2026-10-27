"""Produce identical, no-fix-content prompt cards for L2 and L3 repair trials.

The brief symptom is verifier-derived historical evidence; it is not
a blind naturalistic bug report and should be disclosed as such.
No fixed SHA, fixed tests, implementation diff, or solution is exported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .bugsinpy_reproduce import ALLOWED_CASES, EXPECTED_COMMITS, PROJECT_URLS

SYMPTOMS = {
    "tqdm-6": "A tqdm-wrapped multiprocessing iterator raises AttributeError "
              "on a missing total attribute when obtaining its length.",
    "tornado-5": "A periodic callback does not advance correctly after the "
                 "wall clock jumps backwards.",
    "tornado-6": "Closing Tornado/asyncio event loops leaves more references "
                 "alive than expected.",
    "tornado-7": "The return value of IOLoop.run_in_executor is not awaitable "
                 "with a native Python async/await expression.",
    "tornado-11": "An HTTP request with Transfer-Encoding: Chunked (mixed case) "
                  "fails to parse its chunked body.",
    "tornado-14": "Constructing an explicitly current IOLoop when another is "
                  "already current does not obey the expected rejection rule.",
}


def prepare_tasks(audit_file: Path) -> list[dict]:
    data = json.loads(audit_file.read_text(encoding="utf-8"))
    if data.get("record_type") != "audited_historical_bug_reproduction_only":
        raise ValueError("Expected reviewed six-case historical source")
    rows = data.get("cases")
    if (not isinstance(rows, list) or len(rows) != 6
            or {r["id"] for r in rows} != set(ALLOWED_CASES)
            or any(r.get("llm_verified_success") is not None for r in rows)):
        raise ValueError("Incorrect or prematurely scored historical benchmark")
    tasks = []
    for case_id in ALLOWED_CASES:
        project = case_id.split("-", 1)[0]
        buggy_sha = EXPECTED_COMMITS[case_id][0]
        prompt = (
            f"You are debugging public Python repository {PROJECT_URLS[project]}. "
            f"Use only historical buggy commit {buggy_sha} as your baseline. "
            "Do not view later commits, fixing diffs, or regression tests "
            "from the fix. You may inspect the buggy production code. "
            "Investigate this symptom and return ONLY a minimal unified "
            f"diff changing existing production Python source: {SYMPTOMS[case_id]} "
            "Do not add/edit/delete tests, change dependencies, or run setup scripts."
        )
        tasks.append({
            "case_id": case_id, "project": project,
            "buggy_commit": buggy_sha, "repository": PROJECT_URLS[project],
            "task_type": "code", "prompt": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "symptom_provenance": "historical_verifier_derived_hint_not_blind_bug_report",
            "tiers_to_compare": ["l2", "l3"],
        })
    return tasks


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-audit", type=Path, default=Path(
        "benchmarks/data/bugsinpy_six_historical_reproductions.json"))
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    tasks = prepare_tasks(args.source_audit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for task in tasks:
            f.write(json.dumps(task, ensure_ascii=False) + "\n")
    print("Wrote", len(tasks), "identical L2/L3 task prompts to", args.output)
    print("No remote LLM calls made; no fixed patch/test code exported.")


if __name__ == "__main__":
    main()
