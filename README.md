# Adaptive LLM Router — KEV GPU Lab

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/namyikim/adaptive-llm-router/blob/main/notebooks/kev_a100_colab.ipynb)

An experimental model router that runs **[Kev](https://github.com/jaredpalmer/kev)** on an NVIDIA GPU, tests its model-selection decisions, and lays the groundwork for a quality-verified bottom-up cascade.

> **Important:** Kev is a general-purpose *decision* model, not a validated LLM-capability predictor. The L1/L2/L3 labels in this repo are **illustrative human-assigned examples**, not measurements of whether real LLMs answered correctly. Do not infer routing accuracy, cost savings, or production quality from these examples alone.

## Quick start — Colab A100

1. Click **Open in Colab** above, then `Runtime → Change runtime type → A100 GPU` (A100 availability depends on your Colab subscription).
2. Run notebook cells in order: GPU check → install `uv` and clone upstream Kev → start Kev-4B server → smoke test → sample routing evaluation → optional official benchmark.
3. Download the CSV/JSON outputs from Colab's `/content/outputs`. Outputs and model weights are **not** committed to GitHub.

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
notebooks/kev_a100_colab.ipynb    Colab A100 end-to-end walkthrough
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
uv run --extra serve python -m kev.serve --run jaredpalmer/kev-4b@v1.0 --device cuda --port 8009
```

The upstream repo requires Python 3.12–3.13; its `uv` environment manages this separately from Colab's notebook Python. **Do not** `pip install kev` — that PyPI name belongs to an unrelated package.

## Upstream & license

- Kev repository: https://github.com/jaredpalmer/kev
- Kev-4B checkpoint: https://huggingface.co/jaredpalmer/kev-4b
- Upstream evaluation suites: https://huggingface.co/datasets/jaredpalmer/kev-suites
- This repo contains only independently written integration/experiment files; it **does not vendor Kev weights or code**. Kev is Apache-2.0 licensed.

See [experiment plan](docs/experiment-plan.md) before interpreting metrics.


## Google Drive experiment results

The Colab notebook now includes **Step 10 · Save results to Google Drive**.
Once the experiment cells have finished, run that **single cell** in the same active Colab runtime.
No GPU re-run is needed when `/content/outputs` still exists.

The results are copied to:

```text
MyDrive/adaptive-llm-router/results/kev_a100_YYYYMMDD_HHMMSS_UTC/
├── outputs/
│   ├── router_demo.json
│   └── kev_devtools_benchmark/report.json  # only when official benchmark was enabled
├── kev_gpu_results.zip
└── SAVE_COMPLETE.json  # written last, after successful copies
```

Every save uses a new timestamped folder to avoid overwriting prior runs.
`router_demo.json` measures agreement against **illustrative labels**, not correctness of LLM-generated answers.
For ChatGPT to read private Drive results, the user's Google Drive connection must be authorized.

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
- **Colab:** [Kev A100 + optional paid Claude Gateway smoke test](notebooks/kev_a100_colab.ipynb) (see step 11).
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
