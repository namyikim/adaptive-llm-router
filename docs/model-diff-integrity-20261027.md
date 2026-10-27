# Model patch integrity review — 2026-10-27

## Scope

Continue the existing Anthropic L2/L3 BugsInPy experiment without changing model providers or making another paid call. The most recent reviewed paid run, `40459643599`, saved a summary, prompt and six-case comparison but **no original model response**. Its two `ReplayError` outcomes cannot be reconstructed from those files. This change does not claim to identify or fix the exact cause of that historical run.

PR #26 already archives returned provider text before patch parsing. This follow-up verifies the parser itself using synthetic protocol fixtures, not model answers or official BugsInPy solutions.

## Reproduced defects

Test-first commit `c680c8545409fa9a2e31e24f6cfc151c36eef548` ran the complete repository suite: 166 tests, with seven expected failures in the new regression tests. The previous extractor:

- Accepted a hunk whose declared old/new line counts exceeded the body actually supplied.
- Accepted extra edited lines outside the declared range.
- Dropped a malformed later hunk and returned only the first valid hunk.
- Accepted a missing old-file header.
- Dropped a second file patch placed after prose.
- Selected the first of multiple fenced patches without reporting ambiguity.
- Accepted an unclosed Markdown fence.

These are independently reproduced **parser defects**, not proof of what the missing historical LLM responses contained.

## Change

`model_diff.extract_complete_diff()` now requires exactly one unambiguous, complete text patch. It checks matching old/new file headers and exact old/new hunk body counts. A valid multi-file patch is preserved in full. Surrounding ordinary prose and one closed Markdown fence may be removed; patch bodies, context, edit lines and no-newline annotations are not rewritten. Missing code or hunk counts are never inferred or repaired. Additional candidates or patch-like material outside a completed patch cause an explicit rejection.

The existing case-specific source allowlist remains in place through `inspect_patch()`. This does not broaden the set of editable source files, change the Docker policy, relax paid opt-in, retry API calls, or send official fixes/tests to the model. Existing strict verifier restrictions can still reject otherwise parseable diffs; this is not a general-purpose implementation of every Git diff dialect.

Both the integrated generator and no-cost archived-response replay CLI call `extract_patch()`, so they use the same structural validation. Original response archives and their hashes remain unchanged. An invalid response remains unverified, never a successful bug fix.

## Verification and interpretation

The new regression file includes 11 tests covering the seven reproduced failures, valid multi-file patches, empty added lines, no-newline markers, rejected test-file edits and a real `git apply --check` followed by `git apply` on a disposable synthetic fixture. The fixture changes only a local `value = 1` line to `value = 2`, verifies an unrelated sentinel file remains unchanged, and does not execute project code.

CI runs the full repository unit suite and the existing no-API pinned-source dry run. This is stronger protocol coverage, **not** a paid API evaluation, Docker reproduction, or measured L2/L3 repair result.

Reference for the separate applicability check: https://git-scm.com/docs/git-apply . `git apply --check` checks applicability without applying a patch. It remains necessary against the correct buggy checkout; structural validation alone cannot prove that a patch applies or fixes a bug.

## Next actual evaluation

Use the existing `BugsInPy L2-vs-L3 patch evaluation (opt-in)` workflow on the updated main branch. A new paid run is still separately billable. No paid run is started by this change. A dry run validates preparation only, not model patch correctness. Future archived responses can be reprocessed through `bugsinpy_patch_response_replay` without another API request, but the missing responses from run `40459643599` cannot be recovered by this tool.
