# BugsInPy paired Kev-4B / Kev-9B — 100-case exploratory routing

## Current default (October 2026)

The Colab A100 notebook targets **100 successfully extracted historical test contexts** from **up to 12 diverse public BugsInPy projects** (PySnooper, tqdm, black, thefuck, fastapi, tornado, youtube-dl, scrapy, luigi, cookiecutter, httpie, sanic). It uses deterministic, project-round-robin, seed-based sampling rather than IDs 1–3 only. At most 20 candidates from one project are sampled. The candidate manifest records the exact project/bug IDs, seed, expected count and a SHA-256 digest of sampled source metadata. If fewer than 100 usable cases can be extracted, the report explicitly records the shortfall. Do not state the target was reached unless `cases_written >= 100`.

Default settings in Colab section 11:

```python
RUN_BUGSINPY_COMPARE = True
BUGSINPY_TARGET_SUCCESSFUL_CASES = 100
BUGSINPY_MAX_PER_PROJECT = 20
BUGSINPY_SAMPLE_SEED = 20261026
BUGSINPY_CONTEXT_MODE = "test_only"
```

## Avoiding leakage and understanding what is (not) being tested

Default `test_only` extracts **historical test source** from the `buggy_commit_id` at the test file path supplied by BugsInPy. It NEVER reads fixing-diff filenames and never supplies the fixed patch to the routing model. The known test path itself is a metadata oracle hint, and **there are NO failing exception logs or bug report descriptions unless separately supplied**. It is therefore an exploratory measure of Kev's tier choices on historical test contexts, NOT a blind bug diagnosis or routing quality benchmark. `test_only` may have a lower extraction success rate when the historical test did not exist at the buggy commit.

Legacy mode `fix_diff` is still supported for reproducing the earlier 6-case results. This mode intentionally uses fixing-diff filenames to choose code context, so it has a stronger oracle leak. Mixing modes in one JSONL output is rejected.

No historical bug tests or third-party project code are executed. We intentionally do not attempt to install arbitrary old Python dependency sets inside the GPU notebook. To reproduce failures, use a separate isolated environment with historical Python versions, capped network/CPU and an independently checked buggy-vs-fixed result. Only user-provided external logs named `Project-Id.log` are incorporated and labeled `externally_supplied` rather than automatically reproduced.

## Run All and the storage checkpoints

1. Authenticate Drive with DriveFS or fallback API upload, and verify a remote write/readback **before** GPU work. If both fail, stop.
2. Run 9B A100 smoke and demonstration, and optional official benchmark (disabled by default).
3. Download BugsInPy metadata and build `bugsinpy_sample_manifest.json`. Flush it to Drive immediately.
4. Iterate up to the manifest's candidates, extracting test context until 100 successful cases or candidates exhausted. Persist every successful case to `bugsinpy_cases.jsonl` and every extraction failure to `bugsinpy_collection_errors.jsonl`. Record `bugsinpy_collection_status.json`, including `shortfall`.
5. With Kev-9B running, get model choice for every collected identical input and append results to `bugsinpy_kev_decisions.jsonl` immediately.
6. Stop Kev-9B, launch pinned Kev-4B v1.0 on the same A100, and append its model choices for those exact input hashes.
7. Write `bugsinpy_comparison.json` (per-project tier disagreement, choice probability, latency and invalid/missing cases); create the convenience ZIP and `SAVE_COMPLETE.json`.

Output folder: `MyDrive/adaptive-llm-router/results/kev_a100_<timestamp>_<id>/outputs/`.

Key outputs:

| Filename | Meaning |
| --- | --- |
| bugsinpy_sample_manifest.json | Frozen candidate order, source metadata digest, seed and quotas |
| bugsinpy_cases.jsonl | Public historical test contexts, task mode, source SHA-256 |
| bugsinpy_collection_errors.jsonl | Candidate-level errors that caused shortfall |
| bugsinpy_collection_status.json | Actual cases written and shortfall relative to target |
| bugsinpy_kev_decisions.jsonl | Per-model decisions, exact input hash, per-call duration, failures |
| bugsinpy_comparison.json | Aggregate paired choices and project-level disagreements; **not accuracy** |

Check `RUN_STATUS.json` for progress and `SAVE_COMPLETE.json` for final archive. A completed notebook may contain fewer than 100 successful cases if the older metadata cannot be retrieved. The run's recording of shortfall must be reported. Drive API mode periodically uploads the files; DriveFS mode writes directly to mounted Drive. A fresh Run All creates a new folder and does not resume an interrupted GPU session.

## What the scores do and do not mean

Choice agreement is the fraction of **paired Kev-4B and Kev-9B responses that selected the same tier**, NOT the fraction that solved any bug. Maximum choice probability is not calibrated task success probability. Per-project results help detect any collapse where all inputs are routed to L2. Timing comparisons are sequential and order/warmup-sensitive. Do not report false improvements from historical demo labels or confidence alone.

To estimate real quality and cost savings, independently execute identical debugging prompts on each target LLM, verify against passing tests in isolated environments, prevent fix-patch leakage, and populate benchmark_verified with observed success/failure, latency and cost. This expensive / external execution is explicitly **not** enabled by default.

Sources: https://github.com/soarsmu/BugsInPy and https://github.com/jaredpalmer/kev
