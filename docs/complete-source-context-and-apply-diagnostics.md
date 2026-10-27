# Complete source context and patch-application diagnostics — 2026-10-27

## Why this change

The archived paid experiment [#40463547156](https://github.com/namyikim/adaptive-llm-router/actions/runs/40463547156) reported one L2 regression pass and an unverified L3 candidate. Its prompt omitted the `if disable:` constructor branch. The old excerpt heuristic chose the first occurrence of `def __init__` regardless of its class and then sliced a fixed number of characters; this could exclude the actual `tqdm.__init__` implementation. A valid HEAD check also did not prevent reading locally modified working-tree content.

The L3 verifier saved only `CalledProcessError`, losing whether Git checkout, patch application or another command had failed. The previous partial-source diagnosis suggested a hunk-position problem but was not a full original-checkout test.

## Changes

- `prepare()` now uses **complete allowlisted production files from pinned Git blobs**, not character windows and not working-tree file contents. No official fixed implementation or verifier-test code is added to model input. The legacy excerpt helper remains only for compatibility and is no longer used by prompt generation.
- Each full source section begins at original source line 1. An AST-derived, class-qualified definition index supplies the original method start/end lines. The prompt explicitly distinguishes these locations from prompt/excerpt line numbers and asks for exact original context. Historical syntax that cannot be indexed is marked as such without omitting any source text.
- `source_manifest.json` stores commit, blob ID, SHA-256, byte count, original line count, completeness and definition ranges. `e2e_summary.json` and standalone generation reports record `source_context_version=full-pinned-files-v2` and prompt byte size.
- Files over 200,000 bytes, or combined source over 300,000 bytes, are rejected before generation rather than silently cut. Full source increases input size versus old excerpts; it is **not a guaranteed low-cost prompt**.
- The strict verifier saves bounded local Git stdout/stderr and return code for `patch_apply_check` and `patch_apply`. An inapplicable candidate is `patch_apply_failed`, `candidate_test_executed=false`, `regression_passed=null`, not an environment diagnosis or a tested model failure. Environment/checkout/timeouts remain separately staged inconclusive results.
- Candidate patch bytes and offsets are not rewritten. No `--recount`, relaxed context, automatic retries or paid calls are introduced. Cleanup errors no longer suppress the evidence JSON.

## Test-first evidence

Commit `38ebdfe416e6288bbcec2dedfb2d51b163922d10` ran 171 tests with exactly four new expected failures: required constructor context missing, missing completeness/line provenance, dirty working-tree source replacing the pinned source, and Git apply failure reported only as `inconclusive`. All previous tests passed. The corrections passed the complete suite.

Tests create real small Git repositories and use actual `git apply` errors. They do not call a model or run historical project code. Only the Docker-dependent baseline/fixed execution is mocked in the patch-verifier unit fixture.

## Full original-source audit (no model API)

CI [#40467170388](https://github.com/namyikim/adaptive-llm-router/actions/runs/40467170388) prepared the real pinned `tqdm-6` source through the integrated dry-run and ran `git apply --check` on the **unchanged archived L3 diff**:

| Evidence | Observed value |
| --- | --- |
| Buggy commit | `a4b9c86db548b2d0dbb5af7a6bbdc26ab47e1eec` |
| Complete `tqdm/_tqdm.py` | 46,624 bytes / 1,232 lines |
| `tqdm.__init__` | original lines 626–850 |
| `tqdm.__len__` | original lines 852–856 |
| New prompt | 49,365 UTF-8 bytes, including metadata and symptom |
| Previously omitted `if disable:` | present |
| Original L3 patch SHA-256 | `474de3de40565605b4c4f1d9a01ad498d1a85ab409961f8880f1a12a3d8863ec` |
| Original L3 applicability check | exit 1, `patch failed: tqdm/_tqdm.py:1`, `patch does not apply` |
| Source / patch modified | neither |
| Provider calls / candidate regression tests | 0 / 0 |

This confirms the original candidate is not applicable to the full pinned checkout under the normal Git check. It does **not** show that a rewritten/relocated L3 patch fixes the bug. The test fixture is the exact archived public-project candidate from that run, not an official solution and not input to the source-context builder.

The CPU Actions artifact `source-context-audit-<run-id>` contains the new prompt, source manifest, dry-run summary and `source_and_saved_candidate_audit.json`. Both legacy and new prompt formats remain distinguishable by input hash/version. **Do not combine model outcomes from the different input versions as a paired comparison.**

## Next actual model evaluation

The existing paid workflow and opt-in settings are unchanged. Development/CI here does not start a paid experiment. A new paid trial uses a longer, complete-source prompt and will incur new provider usage; earlier API outputs cannot be regenerated under that new input for free. Existing candidate inspection and parsing remain possible without an API call.

Historical publicly known bugs may be remembered by models. Supplying complete original code and asking not to rely on recalled fixes does not establish an uncontaminated benchmark. Full-suite correctness, general router accuracy, and L3 superiority remain unmeasured.
