# Adaptive LLM Router — KEV-9B GPU Lab

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/namyikim/adaptive-llm-router/blob/main/notebooks/kev_a100_colab.ipynb)

An experimental model router that runs **[Kev-9B](https://huggingface.co/jaredpalmer/kev-9b)** on an NVIDIA GPU, tests its model-selection decisions, and lays the groundwork for a quality-verified bottom-up cascade.

> **Important:** Kev is a general-purpose *decision* model, not a validated LLM-capability predictor. The L1/L2/L3 labels in this repo are **illustrative human-assigned examples**, not measurements of whether real LLMs answered correctly. Do not infer routing accuracy, cost savings, or production quality from these examples alone.

## Latest update: Kev-9B and safer model selection (2026-10-26)

The default Colab A100 checkpoint is now **`jaredpalmer/kev-9b@v1.0`**, pinned for reproducible 4B-to-9B comparisons. Kev-9B requires around **22 GB of GPU resident memory**; the A100 notebook checks for **at least 30 GiB** of available GPU VRAM capacity as conservative headroom (an A100 40 GB or 80 GB is suitable). Kev-27B needs approximately 66 GB including serving buffers and is not a default for A100 40 GB. [Upstream Kev-9B model card](https://huggingface.co/jaredpalmer/kev-9b)

**Routing policy corrected:** Uncertain decisions can promote a lower tier to at least L2 but never demote a selected L3 to L2. For the log/code Gateway, a borderline L1 becomes L2 rather than L3 solely because of a 65% cutoff. API failures still conservatively select L3 with explicit `backend_unavailable` status. Illustrative-label agreement is not real-world task success. The evaluation JSON now includes `raw_label_agreement` and `demoted_count`.

**Google Drive check:** Colab mounts Google Drive at the beginning and writes/reads back `DRIVE_WRITE_VERIFIED.json` in the actual run folder. It also creates `LATEST_RUN.txt` in the results root and writes `RUN_STATUS.json` as it progresses. The presence of those files is a more reliable proof of storage than the Colab output alone. Check that Colab and Drive are using the same Google account. ChatGPT/GitHub cannot inspect a private Google Drive folder without user access.

## Quick start — Colab A100

1. Click **Open in Colab** above, then `Runtime → Change runtime type → A100 GPU` (A100 availability depends on your Colab subscription).
2. Run notebook cells in order: GPU check → install `uv` and clone upstream Kev → start Kev-9B server → smoke test → sample routing evaluation → optional official benchmark.
3. After `Run All`, read `MyDrive/adaptive-llm-router/results/<run-id>/outputs/` and the final `kev_gpu_results.zip`. Results and model weights are **not** committed to GitHub.

No GitHub personal access token is needed to **clone this public repository** in Colab, and **no Hugging Face access token is required for public Kev checkpoints**. Some gated models/datasets may require separate access, but they are not part of the default smoke test. Never paste tokens into notebooks, chat, README, or commits.

## What is implemented

- A `POST /v1/systemone` client using Python standard library (`urllib`), matching the upstream Kev request schema.
- An explicit `choice` routing question with `l1` / `l2` / `l3`, returning model probabilities and conservative uncertainty handling.
- Example questions labelled for **routing sanity checks only**. Reports show agreement with these labels, not true answer quality.
- A separate, pure-Python **bottom-up escalation policy** that only accepts externally verified `passed=True` results. Self-reported confidence is **not** treated as proof of correctness.
- An optional **official Kev devtools-v1 benchmark** using `kev.benchmark` against the local GPU server, reported independently of the example router evaluation.
- Unit tests and lightweight GitHub Actions CI (CPU only, does not download model weights).

## Layout

```text
notebooks/kev_a100_colab.ipynb    Colab A100 Kev-9B end-to-end walkthrough
src/adaptive_llm_router/         Kev API client, routing policy, evaluation
benchmarks/data/demo_routing.jsonl  Small illustrative routing labels
tests/                           CPU-only automated tests
configs/models.json              Example L1/L2/L3 names and relative cost units
docs/experiment-plan.md          Experimental design and safety/validity rules
.github/workflows/tests.yml      GitHub Actions CPU unit tests
```

## Local CPU tests (no GPU/model downloads)

```bash
python -m unittest discover -s tests -v
```

## Standalone routing evaluation (requires Kev server)

```bash
PYTHONPATH=src python -m adaptive_llm_router.evaluate \
  --input benchmarks/data/demo_routing.jsonl \
  --output outputs/router_demo.json
```

Start the upstream server in another terminal first:

```bash
git clone https://github.com/jaredpalmer/kev.git
cd kev
uv sync --extra serve
uv run --extra serve python -m kev.serve --run jaredpalmer/kev-9b@v1.0 --device cuda --port 8009
```

The upstream repo requires Python 3.12–3.13; its `uv` environment manages this separately from Colab's notebook Python. **Do not** `pip install kev` — that PyPI name belongs to an unrelated package.

## Upstream & license

- Kev repository: https://github.com/jaredpalmer/kev
- Kev-9B checkpoint: https://huggingface.co/jaredpalmer/kev-9b
- Upstream evaluation suites: https://huggingface.co/datasets/jaredpalmer/kev-suites
- This repo contains only independently written integration/experiment files; it **does not vendor Kev weights or code**. Kev is Apache-2.0 licensed.

See [experiment plan](docs/experiment-plan.md) before interpreting metrics.


## Colab Drive credential propagation fallback (October 2026)

Some Colab accounts return `MessageError: credential propagation was unsuccessful` when `drive.mount()` is called. This is a known, externally reported Colab authorization failure, **not a Kev model failure**. The notebook now tries DriveFS mount first; on failure, it attempts `google.colab.auth.authenticate_user()` followed by authenticated Google Drive API upload. If either route succeeds, the notebook verifies a file upload by reading the content back from Drive **before running GPU work**. In API mode, outputs are staged locally but uploaded to the same MyDrive run folder after every stage and after each BugsInPy case/decision. `RUN_STATUS.json` records `storage_mode: drivefs|drive_api`.

If **both** Google authorization routes fail, no GPU model is started. The browser/account's authentication must be repaired: use a clean Chrome profile, verify Google account and consent, allow pop-ups/cookies, or file Colab **Help → Send feedback** with the traceback. Python cannot guarantee a fix for a Google-side OAuth failure. User results remain in MyDrive only after an upload has succeeded. The full Drive API mode has CPU/static tests but still needs an end-to-end authorized Colab run.

## Google Drive experiment results — write-through persistence

The [Colab A100 notebook](notebooks/kev_a100_colab.ipynb) **mounts Google Drive at the beginning of Run All**, before starting Kev. Approve Drive access when prompted. It creates a unique run folder and writes the JSON outputs, optional benchmark output, and Kev startup logs **directly to Drive when generated**, rather than waiting for the last cell.

Google Drive: MyDrive/adaptive-llm-router/results/kev_a100_YYYYMMDD_HHMMSS_UTC_XXXXXX/

~~~text
kev_a100_YYYYMMDD_HHMMSS_UTC_XXXXXX/
├── RUN_STATUS.json                  # continuously updated stage progress
├── logs/kev_server.log             # written to Drive from server startup
├── outputs/
│   ├── kev_sample_choices.json
│   ├── router_demo.json
│   ├── kev_gateway_selection.json
│   ├── kev_gateway_claude_test.json
│   ├── kev_gateway_http_test.json
│   └── kev_devtools_benchmark/      # optional
├── kev_gpu_results.zip             # final archive, only when completed
└── SAVE_COMPLETE.json              # emitted only after final success
~~~

**Disconnect recovery:** Even if the last ZIP and SAVE_COMPLETE.json are absent, check RUN_STATUS.json and the completed files under outputs/. An interrupted write may leave a partial JSON file; check that files are readable. Every fresh Run All creates a new folder, without deleting earlier results. A stopped computation is not automatically resumed, and model weights / Python runtime / GPU process are not backed up.

Paid Claude and HTTP integration tests are OFF by default. Full Claude analysis text is excluded unless explicitly enabled; never save credentials or proprietary logs without approval. The demo labels are illustrative, not actual LLM correctness.

## Log and code analysis model routing

The experimental selector now supports **Kev (local), Jev (hosted) and OpenAI Decisions (hosted)** using separate task-specific routing questions for **log/incident analysis** and **code/debugging analysis**. It returns an L1/L2/L3 tier and a configurable Claude model ID; it **does not invoke Claude**. Hosted calls require explicit `--allow-remote` and credentials, and errors/low-confidence choices conservatively select L3. Common secret patterns are redacted, but this is not comprehensive DLP; do not send confidential material to third parties without authorization.

```bash
PYTHONPATH=src python -m adaptive_llm_router.analysis_router --task log --file /path/to/redacted.log --backend kev
PYTHONPATH=src python -m adaptive_llm_router.analysis_router --task code --file /path/to/redacted.py --backend kev
python -m unittest discover -s tests -v
```

For provider setup, exact API examples, model tier configuration, and a **verified log/code outcome evaluation** methodology, read [log/code routing](docs/log-code-routing.md). The new `benchmark_verified` evaluator requires independently measured LLM outcomes; example tier labels are not actual task correctness.

## Kev → Claude execution Gateway (local prototype)

Kev can now choose a real Claude model for **log/code analysis**, and a local API Gateway can invoke the model via Anthropic's official Messages API. The gateway uses **Haiku 5.5 / Sonnet 5.5 / Opus 5.5** for L1/L2/L3 by default. It also supports an **experimental** POST /v1/messages proxy (JSON and SSE, including tool-use passthrough), POST /v1/messages/count_tokens, and session pinning. It does not execute tools, modify files, or guarantee Claude Code integration.

- **Getting started & security:** [Kev Gateway test guide](docs/kev-gateway-test.md)
- **Colab:** [Kev A100 + optional paid Claude Gateway smoke test](notebooks/kev_a100_colab.ipynb) (Drive mount is step 1-2, outputs persist throughout, and final ZIP is step 11).
- **New code:** src/adaptive_llm_router/gateway/

~~~bash
# Run Kev-4B locally at port 8009 first (see above); Anthropic API usage is billed.
export ANTHROPIC_API_KEY="YOUR_API_KEY"
PYTHONPATH=src python -m adaptive_llm_router.gateway --backend kev --enable-remote-llm

curl http://127.0.0.1:8765/healthz
curl -sS http://127.0.0.1:8765/v1/analyze \
  -H 'Content-Type: application/json' \
  -d '{"task_type":"code","content":"What is the bug in: def f(x): return x[0] when x=None?"}'
~~~

The Gateway binds only to localhost; cloud calls are disabled unless explicitly enabled. API credentials live in the environment (never commit them). The proxy is for **testing with sanitized input**. Normal Messages API proxying forwards the original content unchanged, so remove secrets/customer data before using it. When Kev is unavailable the selector conservatively uses L3: check routing.status, and do not interpret that as an accurate router decision. No real performance or cost gain has yet been proven.

## Next diagnostic: 10-case A100 checkpoint-verified pilot

The previous BugsInPy 100-case experiment produced **100/100 identical probability vectors**, but the historical decision rows lacked actual checkpoint attestations. Before rerunning 100 cases, use the [new 10-case A100 pilot](notebooks/kev_identity_10_case_colab.ipynb). It reuses ten diverse inputs from the saved 100-case Drive folder and sequentially loads pinned **Kev-9B then Kev-4B**. Each model must pass a live `GET /v1/models.run` identity check before the notebook accepts its decisions. All individual probabilities, model attestations and separate startup logs persist to a new Drive folder. Full details: [verification procedure](docs/kev-identity-10-case-pilot.md). No paid Claude APIs are invoked.

## Audit existing 100-case runs without GPU

**Do not rerun A100 only to check the previous 100-case equality anomaly.** Open the [CPU-only historical-run audit notebook](notebooks/audit_existing_kevs_colab.ipynb) instead. It reads a previously saved MyDrive BugsInPy run and writes `outputs/bugsinpy_legacy_audit.json`. The audit independently compares complete L1/L2/L3 choice-probability vectors, checks input hashes, duplicate/missing cases, and distinguishes historical unverified labels from checkpoints attested by `/v1/models`.

The earlier 100-case run gave identical 4B/9B tier distributions (95×L2, 5×L3) and identical rounded mean pmax (0.5533). These two equal means alone do not show that every probability vector was equal; and **legacy model labels are not proof of which weights served the request**. Only new runs after PR #10 record live checkpoint identity. See [audit methodology](docs/legacy-kev-result-audit.md).

## Next step: reproduce historical failures before measuring LLM fixes

A new **opt-in**, CPU-only, Docker-isolated BugsInPy reproduction pipeline covers the six cases where Kev-4B/9B diverged: `tqdm-6` and Tornado `5/6/7/11/14`. It compares the same allowlisted historical test(s) on buggy and fixed commits. It never runs BugsInPy `setup.sh` or arbitrary shell scripts, and it distinguishes genuine buggy-fail/fixed-pass evidence from missing dependencies, timeouts and inconclusive tests.

**Next: Four remaining Tornado defects.** The reproducibility runner now handles `tornado-5`, `tornado-7`, `tornado-11` and `tornado-14` as one explicitly opt-in group: select `case_id=tornado-remaining`, `execute=true` in the manual workflow. Historical new/modified tests are verification-only and are NEVER exposed as target LLM inputs. The outputs separately record missing/old tests, test-only overlays, actual failures and fixed-commit passes; historical bug reproduction remains distinct from LLM repair success. [Details](docs/bugsinpy-isolated-reproduction.md).

**Start with GitHub Actions → [BugsInPy historical test reproduction (manual, isolated)](.github/workflows/bugsinpy-reproduction.yml).** The default action is a **non-executing manifest preview**. To run actual third-party historical tests, explicitly enable `execute=true`; GitHub-hosted Docker containers have no runtime network, drop capabilities, use read-only sources and bound CPU/memory/time. Download the Actions artifact to see each case's verification status and logs.

This is **not yet model repair-success measurement**: the historical fixed commit is an independent control, not a model-generated patch. The output keeps `llm_verified_success=null`. See [full methodology and local Docker instructions](docs/bugsinpy-isolated-reproduction.md).

## Large-scale BugsInPy paired Kev-4B / Kev-9B exploratory experiment

**Colab Run All now targets 100 successfully extracted historical test contexts** from 12 public Python projects, sampled with deterministic seed 20261026 using capped, project-round-robin candidate selection. It uses test sources at historical buggy commits and does not consult the fixing diff by default. Unlike the earlier 6-case oracle-assisted pilot, the default `test_only` context mode does not include fixed-file locations; the affected test path is still a metadata hint and no failures are reproduced.

- Kev-9B and then Kev-4B sequentially choose L1/L2/L3 for the **same input text and SHA-256 fingerprint**, with per-case Drive checkpoints.
- New artifacts: `outputs/bugsinpy_sample_manifest.json` (frozen candidate IDs/seed), `outputs/bugsinpy_cases.jsonl`, `outputs/bugsinpy_collection_errors.jsonl`, `outputs/bugsinpy_collection_status.json`, `outputs/bugsinpy_kev_decisions.jsonl`, `outputs/bugsinpy_comparison.json`.
- Colab section 11 defaults: `RUN_BUGSINPY_COMPARE=True`, `BUGSINPY_TARGET_SUCCESSFUL_CASES=100`, `BUGSINPY_CONTEXT_MODE='test_only'`, `BUGSINPY_MAX_PER_PROJECT=20`. Candidate retrieval failures may mean **fewer than 100 cases**; report the `shortfall` field rather than assuming success.
- Actual bug repro and LLM repair outcomes are **not executed**. Compare per-project decision distributions, agreement, and latency only—not routing correctness, success rate, quality or savings.
- For methodology, caveats and future controlled reproduction see [BugsInPy paired evaluation](docs/bugsinpy-paired-evaluation.md).
