# BugsInPy L2 / L3 candidate patch verification

## Scope

Six historical bugs have independently observed buggy-fail / fixed-pass regression tests. This experiment **does not call LLM APIs** and **does not claim model repair success** before actual externally generated patches are supplied and tested.

## 1. Create identical model prompts

```bash
PYTHONPATH=src python -m adaptive_llm_router.bugsinpy_blind_tasks \
  --source-audit benchmarks/data/bugsinpy_six_historical_reproductions.json \
  --output outputs/l2_l3_tasks.jsonl
```

The JSONL contains the same prompt for L2 and L3 for each case, public buggy repository URL and pinned buggy SHA only. **No fixed SHA, verifier tests, fixing diff, or solution is included.** The one-line failure symptom is itself derived from historical verification and therefore this is a paired controlled debugging test, not a completely blind naturalistic bug report. Never give target LLMs the source audit JSON or official fixing commits.

## 2. Independently generate the model patches

Supply each exact same prompt to the chosen external L2 and L3 models; record actual model IDs. Ask each to output only a unified diff against the buggy version. Neither model nor any paid API is invoked by this repository by default.

Store the results as these two separate files (example):

```text
benchmarks/candidate_patches/tornado-7/l2.patch
benchmarks/candidate_patches/tornado-7/l3.patch
```

Only modifications of existing, regular Python production files within the historical project's library are permitted. No tests, new/deleted files, renames, mode changes, binary patches, symlinks, external paths or setup scripts. Maximum 32 KiB and five files per patch. Review for credentials/secrets before putting a patch in a public GitHub repository. These patches must be authentic external model outputs; do not invent them and call that model success.

## 3. Optional manual GitHub Actions verification

Open [BugsInPy L2-L3 patch verification](../.github/workflows/bugsinpy-patch-evaluation.yml) in the GitHub Actions tab. The action uses a separate workflow_dispatch, never runs on normal commits, and requires the exact model-generated patch path above to exist at the selected ref.

| Input | Example |
| --- | --- |
| case_id | tornado-7 |
| tier | l2, then l3 in a separate run |
| model_id | exact external target LLM model identifier |
| execute | false by default; explicit true enables isolated tests |

An execute=true run first checks the patch and historic pins, independently rechecks the buggy-fail/fixed-pass baseline, applies a valid diff **only to a fresh buggy worktree** using git apply, and runs the same verifier-only regression test against the candidate in network-disabled, read-only, resource-capped Docker. Official fixed implementation is never passed to the target LLM or copied to the buggy checkout. Individual candidate/baseline/fixed test logs and the result JSON are saved to Actions Artifacts. GitHub Actions passing is **not** proof of a passing regression.

### Statuses

| status | Meaning |
| --- | --- |
| awaiting_candidate_patch | no external model patch received |
| not_executed | validation-only; no Docker |
| patch_rejected | patch fails structural safeguards |
| baseline_not_reproduced | original bug cannot be reproduced; candidate not scored |
| regression_passed | independently reproduced baseline, and candidate passed all specified regressions |
| regression_failed | candidate failed a specified regression |
| inconclusive | application/environment/collection issue; never counted as pass |

regression_passed is **regression-test-only**, not full-suite patch correctness: full_bugfix_certified always remains false. Model API cost and latency remain null unless measured values are explicitly supplied. Old Python images should be run on disposable isolated CI rather than a workstation.

## 4. Local isolated CLI (optional)

```bash
git clone --depth 1 https://github.com/soarsmu/BugsInPy.git /tmp/BugsInPy
docker build -f docker/bugsinpy-py37.Dockerfile -t adaptive-bugsinpy:py37 .
PYTHONPATH=src python -m adaptive_llm_router.bugsinpy_patch_verifier \
  --dataset-root /tmp/BugsInPy --workspace /tmp/bugsinpy-candidates \
  --output-root outputs/patch_verification \
  --case-id tornado-7 --tier l2 --model-id EXACT_L2_MODEL_ID \
  --patch-file benchmarks/candidate_patches/tornado-7/l2.patch --execute
```

Repeat with l3 and its own patch. Actual measured API costs/times can optionally be supplied through --model-cost-usd and --model-latency-ms. The built-in GitHub workflow does not guess those values.

## 5. Compare only complete independent pairs

```bash
PYTHONPATH=src python -m adaptive_llm_router.bugsinpy_patch_compare \
  --input-dir outputs/patch_verification \
  --output outputs/l2_l3_comparison.json
```

Only real baseline-verified l2/l3 tests with terminal regression_passed or regression_failed outcomes count as a pair. Missing trials are **not imputed as successes or failures**. Overall six-case rates and mean USD costs remain null until all six pairs (and all observed costs, respectively) exist.

Research limitation: these six cases were selected specifically because Kev-4B favored L2 and Kev-9B favored L3. Even full measured results on these six cannot estimate routing accuracy or cost savings across a general workload. No L1 results have been collected; benchmark_verified requires independent L1/L2/L3 outcomes.
