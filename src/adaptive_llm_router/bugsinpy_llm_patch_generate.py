"""Dry-run blind bug prompts; opt-in one paid Anthropic call per L2/L3."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path
from .bugsinpy_patch_verify import PATCH_TARGETS, inspect_patch
from .bugsinpy_reproduce import EXPECTED_COMMITS, ReplayError
from .model_diff import ModelDiffError, extract_complete_diff
from .bugsinpy_source_context import CONTEXT_VERSION, complete_source_context

PILOT = ("tqdm-6", "tornado-6")


def selected_buggy_excerpt(source: str, case_id: str) -> str:
    """Legacy preview helper only; model prompts no longer use this truncation."""
    if len(source) <= 18000:
        return source
    keywords = (
        ("def __len__", "def __iter__", "def __init__")
        if case_id == "tqdm-6"
        else ("def close(", "class AsyncIOLoop", "class BaseAsyncIOLoop",
              "def initialize(", "def _handle_events(", "def clear_current(")
    )
    excerpts = [source[:2200]]
    for word in keywords:
        idx = source.find(word)
        if idx < 0:
            continue
        start = max(0, idx - 400)
        end = min(len(source), idx + 2500)
        excerpts.append(source[start:end])
    excerpts.append(source[-1500:])
    return "\n\n# ... historical buggy source excerpt omitted ...\n\n".join(excerpts)[:18000]


def prepare(case_id: str, buggy_root: Path, failure: str) -> dict:
    if case_id not in PILOT or not 3 <= len(failure) <= 6000:
        raise ValueError("Unapproved case or invalid failure description")
    head = subprocess.check_output(
        ["git", "-C", str(buggy_root), "rev-parse", "HEAD"],
        text=True, timeout=15).strip()
    if head != EXPECTED_COMMITS[case_id][0]:
        raise ReplayError("Expected pinned buggy commit only")
    source_text, manifest = complete_source_context(buggy_root, head, PATCH_TARGETS[case_id])
    prompt = (
        "Fix the historical Python bug. Return ONLY a Git unified diff, with "
        "diff --git, --- and +++ file headers, and @@ hunks. Do not modify tests "
        "or add files. No official patch or verifier test is supplied.\n"
        "All listed source files are COMPLETE and start at source line 1. Use "
        "original file line numbers in @@ headers, not prompt or excerpt line numbers. "
        "The definition index and BEGIN/END labels are metadata, not source: "
        "do not copy them into the patch. Include exact original context lines. "
        "Analyze the supplied buggy source; do not use remembered upstream fixes.\n"
        "Case: " + case_id + "\nObserved failure:\n" + failure +
        "\nOriginal buggy source:\n" + source_text)
    return {"case_id": case_id, "buggy_commit": head, "prompt": prompt,
            "input_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "source_context_version": CONTEXT_VERSION, "source_manifest": manifest,
            "prompt_bytes": len(prompt.encode("utf-8"))}


def extract_patch(answer: str, case_id: str) -> bytes:
    """Extract one complete model patch without dropping hunks or files.

    Surrounding prose or one complete fence may be removed, but missing
    hunk lines/counts and ambiguous additional patches are never repaired.
    Existing case-specific implementation-path restrictions still apply.
    """
    try:
        data = extract_complete_diff(answer)
    except ModelDiffError as exc:
        raise ReplayError(str(exc)) from exc
    inspect_patch(data, case_id)
    return data


def call_anthropic(prompt: str, model: str, key: str, max_tokens: int) -> dict:
    # Avoid optional sampling fields for compatibility with configured models.
    payload = json.dumps({
        "model": model, "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages",
        data=payload, method="POST",
        headers={"content-type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01"})
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=180) as response:
        obj = json.load(response)
    if obj.get("stop_reason") != "end_turn" or obj.get("model") != model:
        raise ReplayError("Incomplete response or unexpected provider model")
    answer = "".join(x.get("text", "") for x in obj.get("content", [])
                     if x.get("type") == "text")
    return {"answer": answer, "model": obj["model"], "id": obj.get("id"),
            "usage": obj.get("usage", {}),
            "elapsed_ms": round(1000 * (time.monotonic() - start), 1)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--case-id", required=True, choices=PILOT)
    p.add_argument("--buggy-checkout", required=True, type=Path)
    p.add_argument("--failure-file", required=True, type=Path)
    p.add_argument("--output-root", required=True, type=Path)
    p.add_argument("--l2-model", default="")
    p.add_argument("--l3-model", default="")
    p.add_argument("--max-tokens", type=int, default=4096)
    p.add_argument("--allow-paid-api", action="store_true")
    args = p.parse_args()
    if not 256 <= args.max_tokens <= 8192:
        p.error("max-tokens must be 256..8192")
    if args.output_root.exists() and any(args.output_root.iterdir()):
        p.error("Output directory must be empty")
    if args.allow_paid_api and (
        not os.environ.get("ANTHROPIC_API_KEY") or not args.l2_model
        or not args.l3_model or args.l2_model == args.l3_model
    ):
        p.error("Paid mode needs key and distinct explicit L2/L3 model IDs")
    request = prepare(args.case_id, args.buggy_checkout,
                      args.failure_file.read_text(encoding="utf-8"))
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "prompt.txt").write_text(request["prompt"], encoding="utf-8")
    (args.output_root / "source_manifest.json").write_text(
        json.dumps(request["source_manifest"], indent=2) + "\n", encoding="utf-8")
    report = {"case_id": args.case_id, "buggy_commit": request["buggy_commit"],
              "input_sha256": request["input_sha256"],
              "source_context_version": request["source_context_version"],
              "source_manifest_file": "source_manifest.json", "prompt_bytes": request["prompt_bytes"],
              "paid_enabled": args.allow_paid_api, "results": {},
              "status": "dry_run_no_api_calls"}
    if args.allow_paid_api:
        report["status"] = "started"
        for tier, model in (("l2", args.l2_model), ("l3", args.l3_model)):
            try:
                result = call_anthropic(request["prompt"], model,
                    os.environ["ANTHROPIC_API_KEY"], args.max_tokens)
                diff = extract_patch(result["answer"], args.case_id)
                (args.output_root / (tier + ".diff")).write_bytes(diff)
                report["results"][tier] = {
                    "status": "candidate_generated", "requested_model": model,
                    "reported_model": result["model"], "response_id": result["id"],
                    "usage": result["usage"], "elapsed_ms": result["elapsed_ms"],
                    "patch_sha256": hashlib.sha256(diff).hexdigest(),
                    "patch_file": tier + ".diff", "verified_patch_success": None}
            except (ValueError, ReplayError, OSError, KeyError) as exc:
                report["results"][tier] = {
                    "status": "failed", "requested_model": model,
                    "error_type": type(exc).__name__, "verified_patch_success": None}
            (args.output_root / "generation_report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        report["status"] = "requests_completed"
    (args.output_root / "generation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))


if __name__ == "__main__":
    main()
