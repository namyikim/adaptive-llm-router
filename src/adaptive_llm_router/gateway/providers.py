"""Anthropic Messages API transport; API keys are never sourced from client headers.

The upstream HTTP response remains open for SSE passthrough. The caller closes it.
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ALLOWED_PATHS = ("/v1/messages", "/v1/messages/count_tokens")
VERSION = "2026-10-21"


class ProviderError(RuntimeError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class ClaudeProvider:
    def __init__(self, api_key: str | None = None, *, base_url: str = "https://api.anthropic.com",
                 timeout: float = 300):
        self.api_key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        if not self.base_url.startswith("https://") and not self.base_url.startswith("http://127.0.0.1:"):
            raise ValueError("Claude upstream must be HTTPS or loopback mock")

    def open(self, path: str, payload: dict, *, headers: dict | None = None):
        if path not in ALLOWED_PATHS:
            raise ValueError("Unsupported upstream path")
        if not self.api_key:
            raise ProviderError("ANTHROPIC_API_KEY is not configured", 503)
        inbound = {k.lower(): v for k, v in (headers or {}).items()}
        outgoing = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": inbound.get("anthropic-version") or VERSION,
            "Accept": "text/event-stream" if payload.get("stream") and path == "/v1/messages" else "application/json",
        }
        for key in ("anthropic-beta", "anthropic-workspace-id"):
            if key in inbound:
                outgoing[key] = inbound[key]
        req = Request(self.base_url + path, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers=outgoing, method="POST")
        try:
            return urlopen(req, timeout=self.timeout)
        except HTTPError as exc:
            # Avoid reflecting untrusted upstream response bodies in server logs.
            raise ProviderError(f"Claude API returned HTTP {exc.code}", exc.code) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderError("Unable to reach Claude API", 502) from exc
