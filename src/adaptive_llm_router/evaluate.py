"""Evaluate Kev *label agreement* on illustrative records (NOT answer quality)."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .routing import TIERS, route_request


def read_cases(path: str | Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record.get("state"), str) or record.get("label") not in TIERS:
                raise ValueError(f"Invalid state or illustrative label at line {n}")
            rows.append(record)
    if not rows:
        raise ValueError("Dataset is empty")
    return rows


def summarize(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("No results to summarize")
    total = len(rows)
    correct = sum(r["prediction"] == r["label"] for r in rows)
    c = Counter((r["label"], r["prediction"]) for r in rows)
    return {
        "n": total,
        "illustrative_label_agreement": correct / total,
        "uncertain_fraction": sum(bool(r["uncertain"]) for r in rows) / total,
        "confusion": {gold: {pred: c.get((gold, pred), 0) for pred in TIERS} for gold in TIERS},
        "note": "Agreement with subjective routing labels; not actual LLM success or cost reduction.",
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--base-url", default="http://127.0.0.1:8009")
    p.add_argument("--min-probability", type=float, default=0.65)
    args = p.parse_args()
    rows = []
    for i, record in enumerate(read_cases(args.input), 1):
        pred = route_request(record["state"], base_url=args.base_url, min_probability=args.min_probability)
        rows.append({
            "id": record.get("id", i), "label": record["label"],
            "prediction": pred.tier, "proposed": pred.proposed_tier,
            "probabilities": pred.probabilities, "p_max": pred.p_max,
            "uncertain": pred.uncertain, "model_latency_ms": pred.latency_ms,
        })
        print(f"{i:>3} {record.get('id', i)}: label={record['label']} predicted={pred.tier} pmax={pred.p_max:.3f}")
    report = {"summary": summarize(rows), "records": rows}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {output}; illustrative_label_agreement={report['summary']['illustrative_label_agreement']:.3f}")


if __name__ == "__main__":
    main()
