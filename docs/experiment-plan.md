# KEV GPU + Adaptive Cascade experimental plan

## Phase 1 — GPU and local server

- Use **Colab A100**, run `nvidia-smi`, confirm GPU available to Kev's `uv` Python (`torch.cuda.is_available()`).
- Clone upstream `jaredpalmer/kev` and install with `uv sync --extra serve`; its `.python-version` is **3.13**.
- Serve `jaredpalmer/kev-4b@v1.0` via `python -m kev.serve --device cuda` on `127.0.0.1:8009`. The initial call downloads the base and adapter.
- Verify the upstream `POST /v1/systemone` returns `answers.start_tier.probabilities`.

## Phase 2 — Minimal routing sanity evaluation

- Evaluate `benchmarks/data/demo_routing.jsonl` with labels l1/l2/l3.
- Record proposed tier, final tier, probability distribution, uncertainty flag, model latency.
- Show a 3×3 confusion matrix and illustrative label agreement.
- **Do not** call this production model-routing accuracy. Those labels are human-assigned expectations and have not been validated against success of any target LLM.

## Phase 3 — Official Kev evaluation

- Optional, *independent from routing accuracy*: benchmark Kev against upstream `evals/devtools-v1` (development partition) using the already-running server:
  `uv run python -m kev.benchmark --remote http://127.0.0.1:8009 --suite evals/devtools-v1 --out /content/outputs/kev_devtools_benchmark`
- This evaluates Kev's calibrated probability predictions against the official labelled evaluation suite. Suites may download frozen data from Hugging Face on first access. On failure, report the error instead of claiming success.
- Development vs test: default benchmark uses development partition; do not tune on official locked test.

## Phase 4 — True LLM routing dataset and cascading

- Sample real requests across Korean and English, difficulty and domains.
- Execute L1, L2, L3 on the **same held-out requests**, with independent correctness checks (unit tests, structured answer comparison, reference answers, blinded human review).
- Store success/fail, actual latency, token usage, price/energy, and task category; split into train/calibration/test BEFORE tuning.
- Learn a policy minimizing expected cost subject to measured accuracy and maximum latency budgets. On uncertain requests, route conservatively and tune thresholds against calibration split.
- Invoke `cascade(execute, verify, start_tier)` only when `verify` independently checks the answer; L3 failure must return `review_required`.
- Evaluate always-L3, static tiers, Kev-direct, Kev-with-cascade with paired requests; report accuracy, escalation frequency, p50/p95 E2E latency, and realized total cost including repeated calls and verifier overhead.

## Notes and limitations

- Kev-4B model card states English; Korean behavior requires new evaluation and possibly LoRA fine-tuning. The sample English dataset is intentional for the first smoke test.
- Zero-shot routing is not a demonstrated Kev capability. Choice probabilities are not model-success probabilities.
- The *sample* `configs/models.json` names/cost units are hypothetical placeholders.
- Do not commit model weights, benchmark outputs, tokens, private questions or credentials. GitHub CI is CPU-only.
