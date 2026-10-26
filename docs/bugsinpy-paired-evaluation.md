# BugsInPy real-code Kev-4B / Kev-9B comparison

## Purpose and data

The A100 Colab notebook now performs a paired local Kev decision experiment using real historical buggy Python code from the public BugsInPy dataset. Initial cases: PySnooper bugs 1,2,3 and tqdm bugs 1,2,3. BugsInPy provides buggy/fixed commit SHA, test file path and historical Python version. The loader checks out public Git history and extracts original code plus relevant test excerpts.

**Limitations:** No historical failing test is automatically executed. If no separately supplied logs exist, log_status is not_reproduced. BugsInPy's fixing diff is used to identify likely Python source filenames (never supplied as a patch to Kev). This is a *location-oracle hint*, not an unbiased benchmark. No target LLM answers, bug fixing, independent pass/fail, cost savings or routing accuracy are measured.

## Colab Run All workflow

1. Google Drive mounts at the start and checks file write/readback. Results and server logs are written directly there.
2. Kev-9B v1.0 starts and completes the existing 12-example evaluation and Gateway choice.
3. If RUN_BUGSINPY_COMPARE=True (default), BugsInPy and its two referenced source repos are cloned. The metadata and actual buggy/test code are saved case-by-case to Drive.
4. The current Kev-9B server evaluates all collected cases, flushing each result immediately to Drive.
5. The Kev-9B process is stopped. Kev-4B v1.0 starts on the same GPU and evaluates the identical inputs; outputs are flushed case by case.
6. A paired report is saved, then the final ZIP and SAVE_COMPLETE.json are written. At the end of the notebook, the active Kev server is 4B, not 9B.

All Kev calls remain local. There is no Claude/OpenAI API charge for this comparison, though Colab GPU usage and initial model downloads consume resources. Kev-4B may download a separate base/adapter. A100 40GB is enough for the sequential experiment, not two simultaneous servers.

## Files in Google Drive

Run folder: MyDrive/adaptive-llm-router/results/kev_a100_<timestamp>_<id>/

- RUN_STATUS.json and DRIVE_WRITE_VERIFIED.json: setup/progress
- logs/kev_server.log: 9B/4B server output
- outputs/bugsinpy_cases.jsonl: actual historical buggy source snippets, metadata, input hash
- outputs/bugsinpy_collection_status.json: collection successes and explicit errors
- outputs/bugsinpy_kev_decisions.jsonl: incremental Kev-9B and Kev-4B choices (including errors)
- outputs/bugsinpy_comparison.json: paired distributions and times, NOT accuracy
- outputs/router_demo.json and outputs/kev_gateway_selection.json: previous sanity checks
- kev_gpu_results.zip and SAVE_COMPLETE.json: final archives/markers, only after completion

If Colab disconnects, case and decision JSONL already flushed to Drive will survive. A currently interrupted line may be truncated and require repair. A new Run All creates a new folder; it does not resume a terminated GPU process automatically.

## Metrics and interpretation

The paired comparison reports n_cases, n_paired, raw and final 4B/9B tier agreement, tier distributions, mean maximum choice probability, model-only and total decision latency, and row-level input hashes. Missing responses are not imputed. Higher decision confidence does not imply higher LLM correctness. The source snippets are selected using a fixing diff filename hint, so this is not a blind correctness benchmark.

## Later steps for independently verified routing accuracy

Use unbiased code context selection, isolated historical Python environments to reproduce failures, and independently verified target LLM outcomes on the same frozen test cases. The existing benchmark_verified module supports measured pass/fail, latency and actual cost. Keep historical fix/patch hidden from routing and target LLMs.

References: https://github.com/soarsmu/BugsInPy and https://github.com/jaredpalmer/kev