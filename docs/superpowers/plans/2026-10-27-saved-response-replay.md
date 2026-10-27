# Saved-response replay implementation plan

**Goal:** Reuse the archived L2/L3 answers from Actions 40468990139 without further provider calls, verify a deterministic formatting-only normalization, and independently test the derived candidates.

**Design / approved direction:** The user asked to continue the proposed separate normalization-and-verification track. Keep the existing strict parser and original scores unchanged. Re-running paid models is unnecessary; silently relaxing the strict parser would mix scoring protocols. Add an explicit assisted path instead.

**Architecture:** A pure normalizer may remove one unambiguous closed Markdown envelope and ordinary surrounding explanation, and may recount existing hunk bodies. It must not invent code, relocate offsets, delete hunks/files or change source lines. Strict structural/path checks follow normalization. A replay runner verifies immutable fixture provenance, applies the same policy to both tiers, and invokes the existing offline, capped Docker verifier. Assisted records have a different evaluation type so the original six-case comparator rejects them.

**Constraints:** No API imports/calls/secrets; no paid workflow changes. Full original response hashes and original strict statuses remain recorded. Only this reviewed public run is included as fixture data. No automatic fixing of inapplicable patches. Preserve original commit, exact raw responses, normalized hash, changed count headers, unchanged body hash, baseline/fixed/candidate logs. Never call normalized outcomes unassisted model successes or general routing accuracy.

## Steps
- [ ] Add failing tests for explicit opt-in, preserved bytes/offsets, ambiguity, malformed bodies, and path restrictions; observe CI failure before implementation.
- [ ] Add pure normalizer and pass full CPU suite, keeping existing strict tests unchanged.
- [ ] Commit exact raw answers and hash manifest from artifact 12717262868; no official implementation or test solution is fixture input.
- [ ] Add replay runner, hash checks, separate assisted evaluation labels, no-overwrite outputs and conservative comparison tests.
- [ ] Run the two archived candidates in the existing bounded offline Docker verifier on a disposable GitHub-hosted runner. Use a one-off development-branch-only workflow trigger; manual workflow execution defaults off after merge. No provider key is supplied.
- [ ] Inspect actual baseline, fixed and candidate logs; document observed results and limits. Review diff, merge only on green CI, and verify main.

**Verification:** CPU unit suite, original strict parser tests, actual git application, independent historical regression tests. A patched-source equality check alone is not a substitute for the requested tests. Any unavailable/failed execution stays null.

**Review focus:** Hidden second patch; miscount versus incomplete body ambiguity; source-path safety; fixture mutation; original/assisted score contamination. Count repair treats the supplied body as the proposed edits, not proof that the model intended no additional edits. Real application and regression verification are still mandatory.
