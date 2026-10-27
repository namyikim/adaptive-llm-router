# Tornado-6 no-provider readiness implementation plan

> Execution: inline implementation using the existing isolated GitHub branch; no provider calls.

**Goal:** Continue the next selected case without repeating paid preparation failures. Verify the complete pinned Tornado input and both historical leak regression tests before requesting any new L2/L3 generation.

**Design:** Retain the existing paid workflow, strict score, and separate normalization score unchanged. Add a narrow read-only readiness auditor and a credential-free manual workflow. A development-branch-only trigger may perform the requested no-provider validation once; remove that trigger before merging. Audit source blobs, hashes, source completeness and not-requested model outcomes. Optional historical evidence must prove both expected buggy tests failed and both official fixed tests passed, with actual per-test logs. No candidate/model success is inferred.

**Alternatives:** Asking the user to run another paid trial immediately risks avoidable expense; changing the paid pipeline or automatically normalizing new outputs changes the experiment protocol. Chosen approach is to reuse the existing dry-run and isolated historical verifier, plus a separate evidence audit.

**Files:** src/adaptive_llm_router/bugsinpy_tornado_readiness.py; tests/test_tornado_readiness.py; .github/workflows/bugsinpy-tornado-readiness.yml; docs/tornado6-readiness.md.

## Constraints
- Python standard library and existing repository functions only.
- No provider key, no model network call, no model change, no mutation of historical source or original evaluation records.
- Source context is full-pinned-files-v2; paths tornado/ioloop.py and tornado/platform/asyncio.py only.
- Historical code execution is restricted to the existing offline, capped Docker runner.
- Static readiness is not historical reproduction; neither is model patch success. Model/API access and actual input token count remain unknown.
- New real model requests remain user-triggered through the existing paid workflow.

## Steps
- [ ] Add tests that fail when the new auditor is absent, including source truncation/tampering, duplicated files, paid outcome contamination and uncollected/mismatched historical tests.
- [ ] Implement read-only audit and run the full CPU suite.
- [ ] Run real pinned dry-run and both historical tests without provider credentials on the disposable GitHub runner.
- [ ] Inspect artifact logs and hashes, record only observed readiness, remove development trigger, review and merge on green CI.

## Review focus
Reject partial source even when the prompt hash is recomputed; match actual Git blobs rather than dirty files; do not count missing tests; never present readiness as L2/L3 quality; preserve all earlier scores.
