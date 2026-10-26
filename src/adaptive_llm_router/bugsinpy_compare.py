"""Paired exploratory Kev-4B vs Kev-9B decisions on identical BugsInPy inputs.

No LLM answer is generated. No verified success rate or correctness label is
claimed. Persist *each* decision promptly for Colab disconnect recovery.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
from pathlib import Path

from .analysis_router import select_analysis_model
from .routing import TIERS

MODEL_LABELS = ("kev-4b@v1.0", "kev-9b@v1.0")


def read_cases(path: Path) -> list[dict]:
    rows, ids = [], set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not isinstance(row.get("input"), str):
            raise ValueError("Every case must have real input text")
        if row.get("source") != "BugsInPy" or row.get("task_type") not in ("code", "log"):
            raise ValueError("Expected BugsInPy code/log case")
        case_id = row.get("id")
        if not isinstance(case_id, str) or case_id in ids:
            raise ValueError("Case IDs must be unique")
        ids.add(case_id)
        rows.append(row)
    if not rows:
        raise ValueError("No cases")
    return rows


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()]


def collect_decisions(cases_path: Path, output_path: Path, model_label: str, *,
                      base_url: str = "http://127.0.0.1:8009") -> dict:
    if model_label not in MODEL_LABELS:
        raise ValueError("Model label must identify a pinned Kev checkpoint")
    cases = read_cases(cases_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    previous = read_rows(output_path)
    completed = {(r["id"], r["model_label"], r["input_sha256"]) for r in previous}
    new_successes = 0
    for case in cases:
        identity = (case["id"], model_label, case["input_sha256"])
        if identity in completed:
            continue
        start = time.perf_counter()
        try:
            decision = select_analysis_model(
                case["task_type"], case["input"], backend="kev",
                base_url=base_url, fallback_on_error=False)
            result = decision.as_dict()
            status = result["status"]
            error = None
        except (Exception) as exc:
            # Mark failures explicitly, do not turn a fallback L3 into a success.
            result, status, error = None, "failed", type(exc).__name__
        elapsed = (time.perf_counter() - start) * 1000
        row = {
            "id": case["id"],
            "model_label": model_label,
            "input_sha256": case["input_sha256"],
            "task_type": case["task_type"],
            "log_status": case.get("log_status"),
            "status": status,
            "error_type": error,
            "decision": result,
            "end_to_end_decision_ms": round(elapsed, 3),
        }
        with output_path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            os.fsync(out.fileno())
        completed.add(identity)
        new_successes += status == "proposed"
        print(f"{model_label} {case['id']}: {status} "
              f"{result.get('tier') if result else '(no decision)'}")
    return {"model_label": model_label, "cases": len(cases),
            "new_successes": new_successes, "output": str(output_path)}


def _mean_or_none(values: list[float]) -> float | None:
    return round(statistics.mean(values), 4) if values else None


def compare_decisions(cases: list[dict], result_rows: list[dict]) -> dict:
    inputs = {c["id"]: c["input_sha256"] for c in cases}
    latest = {}
    for row in result_rows:
        label = row.get("model_label")
        if label not in MODEL_LABELS or row.get("id") not in inputs:
            continue
        if row.get("input_sha256") != inputs[row["id"]]:
            continue  # never silently pair different inputs
        latest[(row["id"], label)] = row
    summaries = {}
    for label in MODEL_LABELS:
        records = [latest[(case_id, label)] for case_id in inputs
                   if (case_id, label) in latest]
        good = [r for r in records if r.get("status") == "proposed" and r.get("decision")]
        summaries[label] = {
            "n_expected": len(cases),
            "n_recorded": len(records),
            "n_successful_decisions": len(good),
            "n_failed_decisions": len(records) - len(good),
            "raw_tier_distribution": {t: sum(r["decision"]["proposed_tier"] == t for r in good) for t in TIERS},
            "selected_tier_distribution": {t: sum(r["decision"]["tier"] == t for r in good) for t in TIERS},
            "mean_max_choice_probability": _mean_or_none([r["decision"]["p_max"] for r in good]),
            "mean_model_latency_ms": _mean_or_none([
                r["decision"]["decision_latency_ms"] for r in good
                if isinstance(r["decision"].get("decision_latency_ms"), (int, float))
                and math.isfinite(r["decision"]["decision_latency_ms"])]),
            "mean_e2e_decision_ms": _mean_or_none([r["end_to_end_decision_ms"] for r in good]),
        }
    paired = []
    for case in cases:
        a, b = (latest.get((case["id"], label)) for label in MODEL_LABELS)
        if a is None or b is None or a.get("status") != "proposed" or b.get("status") != "proposed":
            continue
        ca, cb = a.get("decision"), b.get("decision")
        if not ca or not cb:
            continue
        paired.append({
            "id": case["id"],
            "task_type": case["task_type"],
            "log_status": case.get("log_status"),
            "input_sha256": case["input_sha256"],
            "kev4_raw": ca["proposed_tier"],
            "kev9_raw": cb["proposed_tier"],
            "kev4_final": ca["tier"],
            "kev9_final": cb["tier"],
            "kev4_pmax": ca["p_max"],
            "kev9_pmax": cb["p_max"],
            "kev4_model_latency_ms": ca["decision_latency_ms"],
            "kev9_model_latency_ms": cb["decision_latency_ms"],
        })
    return {
        "evaluation": "paired_actual_buggy_source_routing_exploration",
        "n_cases": len(cases),
        "n_paired": len(paired),
        "raw_agreement_rate": (
            sum(r["kev4_raw"] == r["kev9_raw"] for r in paired) / len(paired) if paired else None
        ),
        "final_agreement_rate": (
            sum(r["kev4_final"] == r["kev9_final"] for r in paired) / len(paired) if paired else None
        ),
        "models": summaries,
        "paired_cases": paired,
        "warnings": [
            "These are real buggy Python source excerpts, but failures were NOT reproduced unless log_status is externally_supplied.",
            "Source files were selected using fixing diff filenames: potential oracle/location leakage; NOT a blind accuracy benchmark.",
            "No independent correctness labels or target LLM success/failure. Choice agreement and confidence are NOT routing accuracy.",
            "Speed comparisons may be affected by warm-up, CUDA state and caching; repeat randomized runs before claims.",
        ],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cases", required=True, type=Path)
    p.add_argument("--results", required=True, type=Path)
    p.add_argument("--summary", type=Path)
    p.add_argument("--model-label", choices=MODEL_LABELS)
    p.add_argument("--base-url", default="http://127.0.0.1:8009")
    args = p.parse_args()
    if args.model_label:
        print(json.dumps(collect_decisions(args.cases, args.results, args.model_label,
                                          base_url=args.base_url), ensure_ascii=False))
    if args.summary:
        report = compare_decisions(read_cases(args.cases), read_rows(args.results))
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
        print("Comparison saved:", args.summary,
              "Paired:", report["n_paired"], "/", report["n_cases"])


if __name__ == "__main__":
    main()
