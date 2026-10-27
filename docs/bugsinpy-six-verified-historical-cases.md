# Audited BugsInPy historical reproductions — 27 October 2026

## Scope and provenance

This is the reviewed, **historical bug-reproduction** evidence for the six final routing disagreements in the 100-case, independently checkpoint-verified Kev-4B versus Kev-9B exploratory test. Each case had Kev-4B choose L2 and Kev-9B choose L3. The historical test evidence **does not establish** whether L2 or L3 is the best target LLM, and no model generated a patch in these runs.

The machine-readable index is [`benchmarks/data/bugsinpy_six_historical_reproductions.json`](../benchmarks/data/bugsinpy_six_historical_reproductions.json). It includes the originating Actions run and artifact IDs, observed error class, and explicitly null AI-patch verification. It does **not** contain fixed implementation patches, regression test code, private data, or a candidate-model debugging prompt.

## Independently inspected evidence

| Historical bug | Source GitHub Actions run | Buggy implementation + verifier-only regression test | Fixed implementation + same test | Reviewed result |
| --- | --- | --- | --- | --- |
| `tqdm-6` | [#40428395903](https://github.com/namyikim/adaptive-llm-router/actions/runs/40428395903) | `AttributeError: 'tqdm' object has no attribute 'total'` | 1 pass | **confirmed by individual logs**; original JSON falsely reported environment failure |
| `tornado-6` | [#40436086706](https://github.com/namyikim/adaptive-llm-router/actions/runs/40436086706) | two leak tests fail: `AssertionError: 10 != 0` and `10 != 1` | both pass | confirmed by logs and JSON |
| `tornado-5` | [#40438878278](https://github.com/namyikim/adaptive-llm-router/actions/runs/40438878278) | backwards-clock callback times wrong, repeating 1010 instead of 1010/1020/1030/1040/1050 | 1 pass | confirmed by logs and JSON |
| `tornado-7` | [#40438878278](https://github.com/namyikim/adaptive-llm-router/actions/runs/40438878278) | `TypeError: object Future can't be used in 'await' expression` with revised regression test | 1 pass | confirmed by logs and JSON |
| `tornado-11` | [#40438878278](https://github.com/namyikim/adaptive-llm-router/actions/runs/40438878278) | uppercase `Chunked` rejected; `{}` instead of `{'foo': ['bar']}` | 1 pass | confirmed by logs and JSON |
| `tornado-14` | [#40438878278](https://github.com/namyikim/adaptive-llm-router/actions/runs/40438878278) | `RuntimeError: current IOLoop already exists` | 1 pass | confirmed by logs and JSON |

The four-case run #40438878278 was explicitly started with `case_id=tornado-remaining`, `execute=true`, at main commit `91dbaf6`. Its artifact `bugsinpy-reproduction-40438878278` (artifact ID `12705356259`) was examined file-by-file. All four buggy tests collected the target test and failed, while all four fixed-commit tests returned exit code 0. Test provenance fields report `fixed_commit_regression_test_only` and `no_implementation_patch_copied=true`. This supersedes earlier **false-positive** run #40437186598, where three test methods did not exist and never ran.

For `tqdm-6`, the earlier machine report was a **false negative** because the output parser confused the printed source line `except ImportError:` with the true `AttributeError`. Do not silently rewrite the old machine report. The other five are both log- and machine-verified.

## Next phase — no simulated accuracy

1. Preserve **the original buggy source and a separately captured failure log** as the LLM debugging evidence. Never use the fixed-commit test file, fixing diff, or fixed implementation as the prompt.
2. Have L2 and L3 target models **independently** attempt a patch against the same buggy baseline. No API calls are enabled by this evidence-only commit.
3. Evaluate each proposed patch in a new isolated, offline, capped container using the verifier-only regression test **plus appropriate existing tests**. For `tornado-7`, the original test passed but the revised test caught the regression.
4. Save a case/model-level record with selected model ID, base commit, candidate diff hash, independent test result, run time, actual API cost and confidence limits. Failed test collection, runtime crashes and absent verification must not count as successes.
5. Use `benchmark_verified.py` only after you have real, independently verified L1/L2/L3 outcomes for a held-out set. Six handpicked disagreements alone cannot measure whole-dataset cost effectiveness or justify selecting Kev-9B over Kev-4B.

**Interpretation:** Six independently inspected historical buggy-fails/fixed-passes results are a verified *test harness foundation*, not six LLM successes, and not a 100% model routing accuracy result.
