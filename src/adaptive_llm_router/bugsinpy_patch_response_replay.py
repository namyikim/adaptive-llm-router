"""Offline reparse of an archived model response, with ZERO additional API calls.

Use the original model response saved by the generator. This program does not
infer a patch from prose or synthesize code; it only extracts and validates a
real unified diff explicitly present in the recorded response. Independent
Docker regression verification must still be run separately.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .bugsinpy_llm_patch_generate import extract_patch
from .bugsinpy_reproduce import ALLOWED_CASES, ReplayError


def replay_response(case_id: str, response_file: Path, output_patch: Path) -> dict:
    if case_id not in ALLOWED_CASES:
        raise ValueError("Unapproved historical bug")
    text = response_file.read_text(encoding="utf-8")
    if output_patch.exists():
        raise ReplayError("Refuse to overwrite existing candidate patch")
    patch = extract_patch(text, case_id)
    output_patch.parent.mkdir(parents=True, exist_ok=True)
    output_patch.write_bytes(patch)
    return {
        "case_id": case_id,
        "response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "patch_sha256": hashlib.sha256(patch).hexdigest(),
        "patch_file": str(output_patch),
        "paid_api_called": False,
        "verified_patch_success": None,
        "status": "candidate_extracted_not_tested",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", choices=ALLOWED_CASES, required=True)
    parser.add_argument("--response-file", type=Path, required=True)
    parser.add_argument("--output-patch", type=Path, required=True)
    args = parser.parse_args()
    result = replay_response(args.case_id, args.response_file, args.output_patch)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
