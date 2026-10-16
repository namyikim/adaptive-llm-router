"""Tiny standard-library client for Kev's TypeSafe-compatible API."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class KevConnectionError(RuntimeError):
    """Raised when the local GPU decision server is not available."""


def post_systemone(
    state: str | dict,
    questions: dict,
    *,
    base_url: str = "http://127.0.0.1:8009",
    timeout: float = 120.0,
    api_key: str | None = None,
) -> dict:
    payload = {"model": "kev-latest", "state": state, "questions": questions}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(
        base_url.rstrip("/") + "/v1/systemone",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except HTTPError as exc:
        snippet = exc.read(500).decode("utf-8", errors="replace")
        raise KevConnectionError(f"Kev HTTP {exc.code}: {snippet}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise KevConnectionError(f"Kev server unreachable: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
        raise ValueError("Unexpected Kev response (missing answers)")
    return data
