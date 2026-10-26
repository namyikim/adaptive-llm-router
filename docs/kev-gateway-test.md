# Kev-selected Claude Gateway — test instructions

## Overview

This **local experimental gateway** uses Kev to route log/code analysis to Claude Haiku 5.5 (L1), Sonnet 5.5 (L2), or Opus 5.5 (L3). It supports direct analysis and a limited Anthropic Messages API proxy with SSE/tool-use passthrough. It does not execute tools, patch files, autonomously validate fixes or guarantee Claude Code compatibility.

Kev is local but selected Claude calls require a **paid Anthropic API key** and an explicit opt-in. Set usage and billing limits in Anthropic Console. Application subscriptions are not interchangeable with API billing.

## Requirements

- Python 3.11+; gateway uses only the standard library.
- Running Kev at http://127.0.0.1:8009 (in same machine/Colab runtime).
- ANTHROPIC_API_KEY in environment when enabling Claude execution.
- Local binding ONLY: this gateway explicitly refuses 0.0.0.0. Colab localhost cannot be accessed from your desktop without a tunnel; do not expose this development server publicly.

## Start gateway

Start Kev using the existing Colab notebook or the upstream Kev server. From the repository root:

~~~bash
export ANTHROPIC_API_KEY="YOUR_API_KEY_FROM_SECRET_MANAGER"
export PYTHONPATH=src
python -m adaptive_llm_router.gateway --port 8765 --backend kev --enable-remote-llm
~~~

Set a separate ROUTER_PROXY_TOKEN environment variable if you want Bearer authentication for this proxy (recommended even on shared localhost). The server uses ANTHROPIC_API_KEY from its own process environment; it never forwards client credentials to Anthropic.

~~~bash
curl http://127.0.0.1:8765/healthz

curl -sS http://127.0.0.1:8765/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{"task_type":"log","content":"Traceback: KeyError on cache lookup. Diagnose likely causes and tests.","max_tokens":400}'
~~~

This produces: analysis, model, tier, routing, usage, stop_reason. Check routing.status. When Kev fails, L3 is selected conservatively with status backend_unavailable; this is not a verified Kev result.

## Quick local routing without calling paid Claude

~~~bash
PYTHONPATH=src python -m adaptive_llm_router.analysis_router \
   --task log --file ./redacted-example.log --backend kev

python -m unittest discover -s tests -v
~~~

The Python tests mock both Kev and Claude; a passing result does NOT establish actual routing or answer quality.

## Messages API streaming and tool forwarding

The gateway implements POST /v1/messages and POST /v1/messages/count_tokens. The former forwards all Anthropic Messages body parameters unchanged except for the selected model. It forwards stream=true SSE events (including tool_use and thinking) as received from Anthropic. It also forwards selected Anthropic version/beta/workspace headers, not incoming credentials.

~~~bash
curl -N http://127.0.0.1:8765/v1/messages \
  -H 'Content-Type: application/json' \
  -H 'anthropic-version: 2026-10-21' \
  -d '{"model":"router-auto","max_tokens":300,"stream":true,"messages":[{"role":"user","content":"Find the bug: def f(x): return x[0] when x=None"}]}'
~~~

When the client explicitly requests one of the configured Claude model IDs, the gateway preserves that choice without routing. To test interception, request model router-auto or set environment ROUTER_FORCE_AUTO=1 on the gateway. Count-tokens requests with router-auto use L3 but do not call Kev.

## Claude Code (experimental)

Official Claude Code documentation supports ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN. Run gateway with ROUTER_PROXY_TOKEN, and in a different terminal:

~~~bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8765
export ANTHROPIC_AUTH_TOKEN="YOUR_ROUTER_PROXY_TOKEN"
export ANTHROPIC_MODEL=router-auto
claude
~~~

Do not set the proxy token equal to the upstream Anthropic API key. The Claude Code client may request endpoints or beta features not yet supported; end-to-end compatibility has not been verified. Tool use is passed back to Claude Code; the gateway never executes the tools itself.

## Session affinity

Send X-Router-Session: your-case-id to pin a model within a multi-step job. The gateway stores only the selected tier and model for one hour. If the client cannot set this header, the gateway hashes the initial user text for best-effort affinity; if conversation compaction drops that text, a continuation may route to L3 instead. For reliable agentic code tasks, use a stable explicit session header (or manually choose a fixed model).

## Safety and scope

- Proxy binds to localhost only. Cloud LLM calls require --enable-remote-llm. Hosted decision providers require --allow-hosted-decisions.
- Local decision selection redacts common secrets; /v1/analyze passes a redacted/truncated excerpt upstream. **/v1/messages transparently forwards original request messages**, not redacted content. Sanitize before transmitting proprietary/private logs or code.
- No rate limiter, budgets, persistent session store, failover verification, production audit logging or retry policies yet.
- Failure to contact Kev selects stronger L3, which may be expensive, so inspect status and costs.
- Measure actual task correctness with independent tests or expert verification. A decision probability is not a probability of successful code diagnosis.

References:
https://github.com/jaredpalmer/kev
https://platform.claude.com/docs/en/api/messages/create
https://platform.claude.com/docs/en/build-with-claude/streaming
https://code.claude.com/docs/en/env-vars
