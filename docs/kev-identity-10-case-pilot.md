# Kev-4B vs Kev-9B — 10-case verified-checkpoint GPU pilot

## Background

An October 26, 2026 BugsInPy historical 100-case experiment showed 100/100 equal full probability vectors according to `bugsinpy_legacy_audit.json`, while `n_both_checkpoint_identities_attested=0` and no model log was present. The saved model labels are insufficient to prove that distinct Kev weights were used.

## New low-cost validation

Open [Colab: Kev checkpoint-verified 10-case pilot](../notebooks/kev_identity_10_case_colab.ipynb) with A100 GPU and Run All. It expects the existing 100-case results at `MyDrive/adaptive-llm-router/results/kev_a100_20261026_083544_UTC_c09a65/outputs/bugsinpy_cases.jsonl`. The previous results are **not modified**.

The notebook selects ten **different, deterministic project-balanced** historical test contexts without reading the previous Kev choices. It saves the exact ID/hash manifest in a new `kev_identity_pilot_<timestamp>_<id>` Drive folder. The inputs are public BugsInPy test contexts, not automatically reproduced failure logs.

The flow, one active GPU server at a time:

1. Mount Drive, check source file exists, make new result folder, verify A100 capacity.
2. Clone GitHub project plus upstream Kev source, save commit IDs.
3. Start `jaredpalmer/kev-9b@v1.0`. Probe `/v1/models`, require the actual `run` to equal the 9B checkpoint. Independently verify again before writing choices. Persist model identity, choices and logs.
4. Stop 9B, then start `jaredpalmer/kev-4b@v1.0`. Verify its `/v1/models.run` and collect decisions on identical input SHA-256 hashes.
5. Reject incomplete paired results or duplicate model identity. Compare **all three L1/L2/L3 probability values**, not rounded means. Save the two model attestations, raw per-case choices, report and summary.

## Files and interpretation

`MyDrive/adaptive-llm-router/results/kev_identity_pilot_.../outputs/` contains:

- `pilot_manifest.json` — selected case IDs/hashes and Git commit IDs
- `pilot_cases.jsonl` — frozen public test inputs
- `pilot_decisions.jsonl` — 20 per-model decision rows with verified checkpoint identities
- `model_attestations.json` — live 9B and 4B reported run IDs plus PID
- `pilot_comparison.json` — paired selection and probability comparisons
- `pilot_summary.json` — short status, exact-vector matches, verification status

`logs/` has separate server log files for both checkpoints. `RUN_STATUS.json` and `SAVE_COMPLETE.json` indicate whether the pilot completed. In case of interruption, intermediate results already written to Drive survive.

**The audit is diagnostic**, not proof of actual bug-fix success or cost optimization. A verified 10/10 vector match with distinct checkpoint identities would still require investigation into model implementations, records, or task/question encoding; it must not be labeled routing success.

Existing 100-case results remain valuable as data, but their historical checkpoint identity cannot be proven retroactively.
