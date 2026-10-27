"""Join independently verified L2 and L3 patch attempts without fabricated data."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from .bugsinpy_reproduce import ALLOWED_CASES

TERMINAL = {"regression_passed", "regression_failed"}


def _valid_observation(record: dict | None, case: str, tier: str) -> bool:
    return (
        isinstance(record, dict)
        and record.get("case_id") == case
        and record.get("tier") == tier
        and record.get("evaluation") == "independent_candidate_patch_regression_only"
        and record.get("executed") is True
        and record.get("baseline_verification_status") == "reproduced_buggy_fail_fixed_pass"
        and record.get("status") in TERMINAL
        and record.get("regression_passed") is (record["status"] == "regression_passed")
        and isinstance(record.get("patch_sha256"), str)
        and isinstance(record.get("model_id"), str) and bool(record["model_id"])
    )


def compare_patch_trials(directory: Path) -> dict:
    rows = []
    for case in ALLOWED_CASES:
        results = {}
        for tier in ("l2", "l3"):
            path = directory / f"{case}_{tier}.json"
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                item = None
            # Invalid or missing data cannot be interpreted as a failure.
            results[tier] = item if _valid_observation(item, case, tier) else None
        complete = all(results.values())
        row = {
            "case_id": case, "complete_independent_pair": complete,
            "l2_model": results["l2"]["model_id"] if results["l2"] else None,
            "l3_model": results["l3"]["model_id"] if results["l3"] else None,
            "l2_regression_passed": results["l2"]["regression_passed"] if results["l2"] else None,
            "l3_regression_passed": results["l3"]["regression_passed"] if results["l3"] else None,
        }
        if complete:
            l2_pass, l3_pass = (
                results["l2"]["regression_passed"], results["l3"]["regression_passed"])
            row["l3_required_for_this_regression"] = (not l2_pass and l3_pass)
            row["l2_sufficient_for_this_regression"] = l2_pass
            row["l3_worse_for_this_regression"] = l2_pass and not l3_pass
        rows.append(row)

    complete_rows = [r for r in rows if r["complete_independent_pair"]]
    result = {
        "evaluation": "paired_L2_vs_L3_independent_regression_outcomes",
        "n_expected_cases": len(ALLOWED_CASES),
        "n_complete_pairs": len(complete_rows),
        "n_incomplete_pairs": len(ALLOWED_CASES) - len(complete_rows),
        "all_six_pairs_complete": len(complete_rows) == len(ALLOWED_CASES),
        "n_l2_regression_passes_in_complete_pairs": sum(
            r["l2_regression_passed"] for r in complete_rows),
        "n_l3_regression_passes_in_complete_pairs": sum(
            r["l3_regression_passed"] for r in complete_rows),
        "n_cases_l3_helped_when_l2_failed": sum(
            r["l3_required_for_this_regression"] for r in complete_rows),
        "n_cases_l3_failed_when_l2_passed": sum(
            r["l3_worse_for_this_regression"] for r in complete_rows),
        "cases": rows,
        "limitations": (
            "Only cases with real, independently verified paired L2 and L3 "
            "patches are counted. These six cases were SELECTED because "
            "Kev-4B L2 and Kev-9B L3 disagreed. They are not a random sample; "
            "regression-only success is not full patch correctness. "
            "No L1 results and no universal Kev routing accuracy estimate."
        ),
    }
    if len(complete_rows) != len(ALLOWED_CASES):
        result["overall_six_case_success_rates"] = None
    else:
        result["overall_six_case_success_rates"] = {
            "l2": result["n_l2_regression_passes_in_complete_pairs"] / len(ALLOWED_CASES),
            "l3": result["n_l3_regression_passes_in_complete_pairs"] / len(ALLOWED_CASES),
        }
    costs = []
    for case in ALLOWED_CASES:
        pair = []
        for tier in ("l2", "l3"):
            p = directory / f"{case}_{tier}.json"
            try:
                record = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                record = None
            if not _valid_observation(record, case, tier):
                break
            cost = record.get("model_cost_usd_observed")
            if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
                break
            pair.append(cost)
        if len(pair) == 2:
            costs.append(pair)
    result["n_pairs_with_actual_costs"] = len(costs)
    result["mean_model_cost_usd_observed"] = (
        {"l2": sum(x[0] for x in costs) / len(costs),
         "l3": sum(x[1] for x in costs) / len(costs)}
        if len(costs) == len(ALLOWED_CASES) else None
    )
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    report = compare_patch_trials(args.input_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("Verified L2/L3 pairs:", report["n_complete_pairs"],
          "/", report["n_expected_cases"])
    print("No missing model outcome was imputed.")


if __name__ == "__main__":
    main()
