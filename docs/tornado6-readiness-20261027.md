# Tornado-6: next-case readiness audit — 2026-10-27

## What actually ran

After the archived tqdm-6 replay, the next selected case was prepared WITHOUT making a new model request. [Actions #40475130903](https://github.com/namyikim/adaptive-llm-router/actions/runs/40475130903) at `71bd27da8d13f7900b2bc3c5ed752c5c64eb1714` ran the full CPU suite, the existing Tornado-6 pipeline in dry-run mode, and both original historical leak tests inside the existing Python 3.7 offline Docker verifier. No provider credential was supplied. A development-branch-only workflow trigger was used once and then removed; the shipped readiness workflow is manual-only and defaults to static checks.

Artifact: `tornado6-readiness-40475130903`, ID `12720520429`, ZIP SHA-256 `fe9a8a2f23f94951f0862c96d516cbd8e1aab2ff6ac21054622a7807699baef9`. The ZIP digest, report and individual historical logs were inspected. This is preparation evidence, NOT a model-generated patch evaluation.

## Complete original input

Buggy source commit: `fb74e4816ccfa7fc6a7abd8c8aab1f415cfc1b13`.

| File | Bytes | Lines | Original definition ranges |
| --- | ---: | ---: | --- |
| `tornado/ioloop.py` | 47,642 | 1,224 | `IOLoop.current` 255–296; `IOLoop.close` 365–390 |
| `tornado/platform/asyncio.py` | 9,621 | 279 | `BaseAsyncIOLoop.initialize` 33–42; `BaseAsyncIOLoop.close` 44–51 |

Both complete pinned source blobs, not dirty working-tree files or truncated excerpts, were present in the common prompt. The entire prompt is **61,895 UTF-8 bytes** with SHA-256 `19d351102806eda43ad10e4367529b1d3c20d0859a2de2051fcadefa9984bb74`, using `full-pinned-files-v2`. Bytes are not billed tokens: input-token count and USD cost are not measured by this no-provider run. No official fixed implementation or verifier test source was added by this change. Existing historically known file selection and test-derived symptoms remain oracle assistance; this is not a blind benchmark.

## Historical test evidence

| Test | Buggy implementation + verifier-only test | Official fixed version |
| --- | --- | --- |
| `LeakTest.test_ioloop_close_leak` | Real assertion failure `10 != 0`; exit 1 | One test, `OK`; exit 0 |
| `LeakTest.test_asyncio_close_leak` | Real assertion failure `10 != 1`; exit 1 | One test, `OK`; exit 0 |

Original missing-test logs were retained, but were NOT counted as actual bug failures. On the buggy checkout, the reviewed fixed-commit TEST file alone was mounted read-only; no implementation fix was copied. Readiness requires both expected selectors, matching commands, true assertion-failure logs and fixed-pass logs. Environment errors or `_FailedTest` placeholders cannot pass the readiness audit.

`ready_for_pilot.json` records source readiness and historical reproduction separately, `new_provider_calls=0`, `model_quality_measured=false`, and L2/L3 model outcomes both `null`. Existing tqdm original and format-assisted scores were not altered.

## Tests and implementation

- Six auditor tests were committed first at `23d5f74305d491e1128f2c1f928f9d8db512defe`. CI ran 187 tests with exactly six expected failures because the new auditor did not exist; the 181 existing tests passed.
- The auditor validates actual pinned Git blobs, complete source content in the prompt, manifest/hash equality, not-requested model status, and optional independent historical logs.
- Fixtures use real small Git repositories. Added tests reject recomputed-hash truncation, duplicated/incomplete manifests, measured results disguised as readiness and missing historical tests. Dirty working-tree bytes never replace pinned source.
- The final workflow contract forbids provider secrets, paid flags, schedules and push/PR execution triggers. No paid pipeline or normalization-policy default changed.

## Next user-triggered model evaluation

The readiness checks above are already done; there is no need to repeat them or rerun the tqdm-6 paid trial. Use the EXISTING [BugsInPy L2-vs-L3 patch evaluation](https://github.com/namyikim/adaptive-llm-router/actions/workflows/bugsinpy-llm-eval.yml), select the current `main`, and start a NEW run:

| Input | Value |
| --- | --- |
| `case_id` | `tornado-6` |
| `allow_paid_api` | `true` only when authorizing new billed calls |
| `execute_patch_tests` | `true` |
| `l2_model` | `claude-sonnet-5-5` (same configured model ID as prior experiment) |
| `l3_model` | `claude-opus-5-5` (same configured model ID as prior experiment) |

The already configured provider secret is used by that separate paid workflow. Do not put its value in the form. Readiness does not establish model availability, account credit or future request success. A paid run makes new model requests; GitHub reruns can bill again. No new model request was performed by this readiness work.

Accept model success only after the candidate patch applies and BOTH leak tests execute and pass. Missing/invalid candidate formatting is recorded separately; any later formatting assistance remains a distinct result, not an overwrite of the original trial. One selected case does not establish full-suite correctness or overall Kev routing accuracy.
