"""Offline replay of independently VERIFIED model outcomes, not heuristic tier labels.

Input is a held-out JSONL dataset, with the SAME task's outcomes measured for
every candidate tier and any available decision-backend predictions.
No actual LLM or decision API is invoked by this module.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from .routing import TIERS


def read_verified_cases(path: str | Path) -> list[dict]:
    records = []
    ids = set()
    with open(path, encoding="utf-8") as stream:
        for index, line in enumerate(stream, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            identifier = record.get("id")
            if not isinstance(identifier, str) or not identifier or identifier in ids:
                raise ValueError(f"Missing or duplicate ID at line {index}")
            ids.add(identifier)
            if record.get("split") != "test" or record.get("task_type") not in ("log", "code"):
                raise ValueError(f"Only held-out log/code test records accepted at line {index}")
            outcomes = record.get("outcomes")
            if not isinstance(outcomes, dict) or set(outcomes) != set(TIERS):
                raise ValueError(f"Outcomes for all 3 tiers required at line {index}")
            for tier, outcome in outcomes.items():
                if not isinstance(outcome, dict) or not isinstance(outcome.get("passed"), bool):
                    raise ValueError(f"{tier} must have externally verified boolean passed")
                for key in ("cost_usd", "latency_ms", "verifier_cost_usd", "verifier_latency_ms"):
                    value = outcome.get(key, 0 if key.startswith("verifier") else None)
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                        raise ValueError(f"{tier}.{key} must be finite nonnegative number")
            predictions = record.get("predictions", {})
            if not isinstance(predictions, dict):
                raise ValueError("predictions must be object")
            for provider, prediction in predictions.items():
                if not isinstance(prediction, dict) or prediction.get("tier") not in TIERS:
                    raise ValueError(f"Invalid tier for provider {provider}")
                for key in ("decision_cost_usd", "decision_latency_ms"):
                    value = prediction.get(key)
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                        raise ValueError(f"Missing/invalid {key} for provider {provider}")
            records.append(record)
    if not records:
        raise ValueError("No test cases")
    return records


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def evaluate_strategy(records: list[dict], *, backend: str | None = None,
                      start_tier: str = "l3") -> dict:
    """Offline cascade: stop only on independent verification, not self-confidence."""
    if not records:
        raise ValueError("No cases")
    if backend is None and start_tier not in TIERS:
        raise ValueError("Unknown start tier")
    total_costs, total_times = [], []
    n_passed, n_escalated, n_attempts = 0, 0, 0
    by_kind = {"log": {"n": 0, "passed": 0}, "code": {"n": 0, "passed": 0}}
    for row in records:
        prediction = row.get("predictions", {}).get(backend) if backend else None
        if backend and not prediction:
            raise ValueError(f"Missing decision from {backend} for {row['id']}")
        tier = prediction["tier"] if prediction else start_tier
        spend = prediction["decision_cost_usd"] if prediction else 0.0
        elapsed = prediction["decision_latency_ms"] if prediction else 0.0
        passed = False
        attempts = 0
        for candidate in TIERS[TIERS.index(tier):]:
            outcome = row["outcomes"][candidate]
            spend += outcome["cost_usd"] + outcome.get("verifier_cost_usd", 0.0)
            elapsed += outcome["latency_ms"] + outcome.get("verifier_latency_ms", 0.0)
            attempts += 1
            if outcome["passed"]:
                passed = True
                break
        total_costs.append(spend)
        total_times.append(elapsed)
        n_passed += int(passed)
        n_attempts += attempts
        n_escalated += int(attempts > 1)
        kind = row["task_type"]
        by_kind[kind]["n"] += 1
        by_kind[kind]["passed"] += int(passed)
    n = len(records)
    return {
        "n": n, "verified_success_rate": n_passed / n,
        "review_required": n - n_passed,
        "escalation_rate": n_escalated / n,
        "mean_attempts": n_attempts / n,
        "mean_total_cost_usd": sum(total_costs) / n,
        "p50_e2e_latency_ms": _percentile(total_times, .50),
        "p95_e2e_latency_ms": _percentile(total_times, .95),
        "by_task_type": {k: {"n": v["n"], "verified_success_rate": v["passed"] / v["n"] if v["n"] else None}
                         for k, v in by_kind.items()},
    }


def compare(records: list[dict]) -> dict:
    strategies = {
        "always_l3": evaluate_strategy(records, start_tier="l3"),
        "cascade_l2": evaluate_strategy(records, start_tier="l2"),
        "cascade_l1": evaluate_strategy(records, start_tier="l1"),
    }
    providers = set().union(*(r.get("predictions", {}).keys() for r in records))
    incomplete = {}
    for provider in sorted(providers):
        missing = [r["id"] for r in records if provider not in r.get("predictions", {})]
        if missing:
            incomplete[provider] = missing
        else:
            strategies[provider] = evaluate_strategy(records, backend=provider)
    baseline = strategies["always_l3"]["verified_success_rate"]
    for result in strategies.values():
        result["success_delta_vs_always_l3"] = result["verified_success_rate"] - baseline
    return {
        "evaluation": "held_out_verified_replay",
        "n": len(records),
        "strategies": strategies,
        "incomplete_backends": incomplete,
        "limitations": "Only as valid as the independent verification and measured cost/latency; "
                       "no per-model self-rating as correctness. Cannot infer performance from illustrative labels.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="held-out verified outcomes JSONL")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = compare(read_verified_cases(args.input))
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {path}: {report['n']} independently verified test records")


if __name__ == "__main__":
    main()
