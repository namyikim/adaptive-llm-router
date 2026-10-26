"""Audit SAVED BugsInPy Kev-4B/9B results without loading GPU models.

Old runs may have no trustworthy model identity: per-row labels are not proof.
This tool deliberately distinguishes numerical equality from validated identity.
No network calls, no LLM APIs, no arbitrary project-code execution.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import Counter
from pathlib import Path

LABELS = ("kev-4b@v1.0", "kev-9b@v1.0")
TIERS = ("l1", "l2", "l3")
CHECKPOINTS = {"kev-4b@v1.0": "jaredpalmer/kev-4b@v1.0",
               "kev-9b@v1.0": "jaredpalmer/kev-9b@v1.0"}


def read_jsonl(path: Path) -> tuple[list[dict], list[dict]]:
    rows, errors = [], []
    if not path.exists():
        return rows, [{"line": None, "reason": "missing_file", "file": path.name}]
    with path.open(encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("JSONL value not an object")
            except (ValueError, UnicodeError):
                errors.append({"line": n, "reason": "invalid_jsonl"})
                continue
            rows.append(row)
    return rows, errors


def _probabilities(decision: dict | None) -> dict[str, float] | None:
    if not isinstance(decision, dict):
        return None
    p = decision.get("probabilities")
    if not isinstance(p, dict) or set(p) != set(TIERS):
        return None
    try:
        values = {t: float(p[t]) for t in TIERS}
    except (ValueError, TypeError):
        return None
    if (not all(math.isfinite(v) and 0 <= v <= 1 for v in values.values())
            or abs(sum(values.values()) - 1) > .025):
        return None
    return values


def _attested(row: dict, label: str) -> bool:
    identity = row.get("server_identity")
    return (isinstance(identity, dict) and identity.get("verified") is True
            and identity.get("checkpoint_run") == CHECKPOINTS[label]
            and identity.get("reported_run", identity.get("checkpoint_run")) == CHECKPOINTS[label])


def audit_results(rows: list[dict], *, cases: list[dict] | None = None,
                  server_log: str = "") -> dict:
    """Return provenance-aware paired comparison for historical or new saved rows."""
    latest, invalid, duplicates = {}, 0, 0
    case_hashes = {}
    if cases is not None:
        case_hashes = {str(c.get("id")): c.get("input_sha256") for c in cases}
    for row in rows:
        label, case_id, sha = row.get("model_label"), row.get("id"), row.get("input_sha256")
        if not isinstance(case_id, str) or label not in LABELS or not isinstance(sha, str) or not sha:
            invalid += 1
            continue
        if cases is not None and (case_id not in case_hashes or case_hashes[case_id] != sha):
            invalid += 1
            continue
        key = (case_id, label)
        if key in latest:
            duplicates += 1
        latest[key] = row

    pairs, missing = [], []
    case_ids = sorted(case_hashes if cases is not None else {cid for cid, _ in latest})
    for case_id in case_ids:
        a, b = (latest.get((case_id, label)) for label in LABELS)
        if a is None or b is None:
            missing.append(case_id)
            continue
        if a["input_sha256"] != b["input_sha256"]:
            invalid += 1
            missing.append(case_id)
            continue
        if a.get("status") != "proposed" or b.get("status") != "proposed":
            missing.append(case_id)
            continue
        pa, pb = _probabilities(a.get("decision")), _probabilities(b.get("decision"))
        if pa is None or pb is None:
            invalid += 1
            missing.append(case_id)
            continue
        da, db = a["decision"], b["decision"]
        if (da.get("proposed_tier") not in TIERS or db.get("proposed_tier") not in TIERS
                or da.get("tier") not in TIERS or db.get("tier") not in TIERS):
            invalid += 1
            missing.append(case_id)
            continue
        maxdiff = max(abs(pa[t] - pb[t]) for t in TIERS)
        pairs.append({
            "id": case_id,
            "raw_match": da["proposed_tier"] == db["proposed_tier"],
            "final_match": da["tier"] == db["tier"],
            "exact_vector_match": pa == pb,
            "pmax_exact_match": da.get("p_max") == db.get("p_max"),
            "max_abs_probability_diff": maxdiff,
            "attested_both": _attested(a, LABELS[0]) and _attested(b, LABELS[1]),
            "kev4_tier": da["tier"],
            "kev9_tier": db["tier"],
        })

    n = len(pairs)
    equalvec = sum(p["exact_vector_match"] for p in pairs)
    both_attested = sum(p["attested_both"] for p in pairs)
    dist = {}
    for label in LABELS:
        selected = [row for (cid, name), row in latest.items()
                    if name == label and row.get("status") == "proposed"
                    and _probabilities(row.get("decision")) is not None]
        dist[label] = {
            "n_valid_decisions": len(selected),
            "n_attested": sum(_attested(row, label) for row in selected),
            "raw_tiers": dict(Counter(r["decision"].get("proposed_tier") for r in selected)),
            "selected_tiers": dict(Counter(r["decision"].get("tier") for r in selected)),
            "mean_p_max": (round(statistics.mean(float(r["decision"]["p_max"]) for r in selected), 6)
                           if selected else None),
        }

    # Log text may show a *launch request* but does not cryptographically attest
    # which weights produced each request. Never promote it to verified provenance.
    log_refs = {label: len(re.findall(re.escape(ref), server_log))
                for label, ref in CHECKPOINTS.items()}
    status = ("verified_checkpoint_pairs" if n and both_attested == n
              else "historical_unattested_comparison" if n else "insufficient_paired_data")
    flags = []
    if n and equalvec == n:
        flags.append("all_probability_vectors_identical")
    if n and both_attested < n:
        flags.append("checkpoint_identity_not_proven_in_saved_rows")
    if n and all(p["kev4_tier"] == "l2" for p in pairs):
        flags.append("all_kev4_final_tiers_l2")
    if n and all(p["kev9_tier"] == "l2" for p in pairs):
        flags.append("all_kev9_final_tiers_l2")
    return {
        "audit_version": 1,
        "status": status,
        "n_raw_rows": len(rows),
        "n_unique_model_case_keys": len(latest),
        "n_invalid_or_mismatched_rows": invalid,
        "n_duplicate_model_case_keys": duplicates,
        "n_expected_cases": len(case_ids),
        "n_valid_pairs": n,
        "n_missing_or_failed_pairs": len(missing),
        "first_missing_case_ids": missing[:15],
        "n_exact_pmax_matches": sum(p["pmax_exact_match"] for p in pairs),
        "n_exact_probability_vector_matches": equalvec,
        "n_raw_tier_matches": sum(p["raw_match"] for p in pairs),
        "n_final_tier_matches": sum(p["final_match"] for p in pairs),
        "mean_max_abs_probability_diff": (round(statistics.mean(p["max_abs_probability_diff"]
                                                                 for p in pairs), 9) if pairs else None),
        "max_abs_probability_diff": (round(max(p["max_abs_probability_diff"] for p in pairs), 9)
                                     if pairs else None),
        "n_both_checkpoint_identities_attested": both_attested,
        "models": dist,
        "requested_checkpoint_mentions_in_log": log_refs,
        "log_evidence_note": "Textual checkpoint references may be launch arguments; they are NOT actual per-request attestation.",
        "flags": flags,
        "differing_examples": sorted(
            [p for p in pairs if not p["exact_vector_match"]],
            key=lambda p: p["max_abs_probability_diff"], reverse=True)[:10],
        "notes": [
            "Paired tier agreement is NOT the same as correctness or actual bug repair success.",
            "An old run without /v1/models.run attestation cannot prove which checkpoint produced its rows.",
            "Equal means can hide per-case differences. Compare complete L1/L2/L3 vectors.",
            "Selected code/test context and missing failure logs prevent calibrated routing-accuracy estimates.",
        ],
    }


def audit_folder(run_root: Path) -> dict:
    out = run_root / "outputs"
    rows, row_errors = read_jsonl(out / "bugsinpy_kev_decisions.jsonl")
    cases, case_errors = read_jsonl(out / "bugsinpy_cases.jsonl")
    logpath = run_root / "logs" / "kev_server.log"
    log = logpath.read_text(encoding="utf-8", errors="replace") if logpath.exists() else ""
    report = audit_results(rows, cases=cases or None, server_log=log)
    report["source_run_directory"] = run_root.name
    report["input_parse_errors"] = {"decisions": row_errors, "cases": case_errors}
    report["log_present"] = logpath.exists()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True,
                        help="A previously saved MyDrive/../kev_a100_<run> directory")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report = audit_folder(args.run_root)
    output = args.output or args.run_root / "outputs" / "bugsinpy_legacy_audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("Saved:", output)


if __name__ == "__main__":
    main()
