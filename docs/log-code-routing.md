# Log and code analysis — Kev, Jev, OpenAI Decisions

## Scope
This router **selects** which LLM should analyze source code or application logs. It DOES NOT execute Claude, inspect a Git repository, run tests, fix bugs, or verify the selected model's work.

Decision backends:
- Kev: local System One endpoint, localhost:8009 by default (no API key required by default)
- Jev: TypeSafe System One endpoint, TYPESAFE_API_KEY
- OpenAI: Decisions API with gpt-6-luna, OPENAI_API_KEY

All backends return the same normalized L1/L2/L3 tier and a configurable model ID in configs/analysis_models.json. The supplied Claude IDs are **illustrative candidates** and require access/availability checks.

## Privacy and safety

Code and logs may contain secrets, customer identifiers and proprietary material. The router redacts **common** token formats, bearer headers and password/key assignments, and truncates oversized input. This is **NOT comprehensive DLP**. Remove all company-private material and obtain permission before calling a hosted API.

- Hosted Jev and OpenAI require explicit --allow-remote and an environment API key.
- Do not store keys, source logs, or provider credentials in version control or report files.
- Input (including code comments and logs) is untrusted; never execute embedded instructions.
- Bad responses, refusals or API failures select L3 with backend_unavailable status (or use --strict to raise). An unavailable provider is not counted as correct routing.
- Uncertain predictions (maximum probability below 0.65 by default) route conservatively to L3.

## Run the selector

Start Kev using the existing Colab A100 notebook or a local server. In the repository root:

~~~bash
PYTHONPATH=src python -m adaptive_llm_router.analysis_router \
  --task log --file /path/to/redacted.log --backend kev

PYTHONPATH=src python -m adaptive_llm_router.analysis_router \
  --task code --file /path/to/redacted.py --backend kev
~~~

For hosted decision APIs (only with an approved sanitized input):

~~~bash
export TYPESAFE_API_KEY=...  # read from your local secrets manager
PYTHONPATH=src python -m adaptive_llm_router.analysis_router \
  --task log --file /path/to/redacted.log \
  --backend jev --allow-remote

export OPENAI_API_KEY=...
PYTHONPATH=src python -m adaptive_llm_router.analysis_router \
  --task code --file /path/to/redacted.py \
  --backend openai --allow-remote
~~~

The output contains tier, target_model_id, decision_backend, probabilities, p_max, uncertain, status and verified_success=null. **Probability of a tier is NOT probability that the selected LLM can solve the task.** Customize Claude model IDs in configs/analysis_models.json; this code only chooses a model ID.

## Measured evaluation: same task, every LLM

The original demo_routing.jsonl labels were illustrative. They are NOT successful answers from actual models.

For objective routing evaluation:
1. Gather Korean/English logs and code defects, sanitize them, and create task-specific independent verifiers (reproduction/unit tests, known fixes, blinded expert review). Split by issue/repository into train, calibration and frozen test.
2. On each held-out test task, actually execute target L1, L2 and L3 using the same evidence. Capture independently verified pass/fail, total API cost, latency and verifier overhead for every tier. The selector does not do these executions.
3. Run Kev, Jev and OpenAI Decisions on the same **approved redacted** inputs, and record each predicted tier plus *measured* decision cost and latency.
4. Add to a local private JSONL file, one record per task. Every tier's measured outcome is required for fair comparison. Providers with missing predictions are excluded, not filled with guessed values.
5. Replay with benchmark_verified.py and compare always-L3, cascade-L1, cascade-L2 and each provider. Report success, cost, escalation, p50/p95 end-to-end latency and log/code performance separately.

Schema example only. **Numbers below are invented placeholders, NOT experiment results**:

~~~json
{
  "id": "anonymized-case-001",
  "split": "test",
  "task_type": "code",
  "outcomes": {
    "l1": {"passed": false, "cost_usd": 0.001, "latency_ms": 500},
    "l2": {"passed": true, "cost_usd": 0.01, "latency_ms": 1500},
    "l3": {"passed": true, "cost_usd": 0.05, "latency_ms": 3000}
  },
  "predictions": {
    "kev": {"tier": "l2", "decision_cost_usd": 0.0, "decision_latency_ms": 75},
    "jev": {"tier": "l2", "decision_cost_usd": 0.00002, "decision_latency_ms": 125},
    "openai": {"tier": "l3", "decision_cost_usd": 0.00005, "decision_latency_ms": 100}
  }
}
~~~

The verifier_cost_usd and verifier_latency_ms fields can be supplied under each outcome and are included in total costs. For a quality-retention calculation compare with always-L3 using the same task set. Validate correctness independently: an LLM's self-reported confidence does not prove its answer.

~~~bash
PYTHONPATH=src python -m adaptive_llm_router.benchmark_verified \
  --input /private/heldout_verified.jsonl \
  --output outputs/verified_comparison.json

python -m unittest discover -s tests -v
~~~

## Milestones

- [x] Task-specific log/code routing prompt and preprocessing.
- [x] Kev, Jev and OpenAI typed decision adapters with response normalization.
- [x] Explicit hosted-provider opt-in and conservative error/uncertainty fallback.
- [x] Editable Claude model mapping, selector-only CLI.
- [x] CPU-only tests with mock API responses.
- [x] Offline replay of independent verified outcomes with cost/latency accounting.
- [ ] Live benchmark all three providers with approved credentials and GPU runtime.
- [ ] Collect verified held-out real code/log tasks and determine quality/cost thresholds.
- [ ] Implement an actual Claude execution gateway, with independent verification, security guardrails, usage logs and rate limits.

Links: https://github.com/jaredpalmer/kev ; https://developers.openai.com/api/docs/guides/decisions ; https://api.typesafe.ai/v1/systemone
