"""Local-only, authenticated-when-configured, experimental Messages API gateway.

No code execution here: tool_use events are forwarded to the client for approval
and handling. Claude API calls require an explicit startup flag.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .core import GatewayInputError, GatewayService
from .providers import ClaudeProvider, ProviderError

MAX_BODY_BYTES = 4 * 1024 * 1024


class GatewayHandler(BaseHTTPRequestHandler):
    service: GatewayService
    allow_cloud_calls: bool = False
    proxy_token: str = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Do not write request paths/headers, code snippets or tokens to stdout.
        pass

    def _json(self, status: int, data: dict, *, extra_headers: dict | None = None):
        output = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(output)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(output)

    def _authorized(self) -> bool:
        if not self.proxy_token:
            return True  # server enforces loopback binding only
        supplied = self.headers.get("X-Router-Key", "")
        if not supplied:
            authorization = self.headers.get("Authorization", "")
            if authorization.startswith("Bearer "):
                supplied = authorization[len("Bearer "):]
        return hmac.compare_digest(supplied, self.proxy_token)

    def _body(self) -> dict:
        raw_size = self.headers.get("Content-Length")
        if raw_size is None or not raw_size.isdigit():
            raise GatewayInputError("Content-Length required")
        size = int(raw_size)
        if size < 1 or size > MAX_BODY_BYTES:
            raise GatewayInputError("Request must be 1..4MiB")
        data = json.loads(self.rfile.read(size))
        if not isinstance(data, dict):
            raise GatewayInputError("Expected a JSON object")
        return data

    def do_GET(self):
        if self.path == "/healthz":
            self._json(200, {"status": "ok", "backend": self.service.decision_backend,
                             "claude_calls_enabled": self.allow_cloud_calls,
                             "claude_api_key_configured": bool(self.service.provider.api_key)})
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self):
        if self.path not in ("/v1/analyze", "/v1/messages", "/v1/messages/count_tokens"):
            self._json(404, {"error": "not_found"})
            return
        if not self._authorized():
            self._json(401, {"error": "unauthorized"})
            return
        if not self.allow_cloud_calls:
            self._json(403, {"error": "cloud_calls_disabled",
                             "message": "Restart gateway with --enable-remote-llm after reviewing data permissions"})
            return
        try:
            data = self._body()
            if self.path == "/v1/analyze":
                self._json(200, self.service.analyze(
                    data.get("task_type"), data.get("content"),
                    max_tokens=data.get("max_tokens", 1024)))
                return
            if self.path == "/v1/messages/count_tokens":
                payload = self.service.route_count_tokens(data)
                selection = {"tier": "none", "target_model_id": payload["model"]}
            else:
                routed = self.service.route_messages(
                    data, session_header=self.headers.get("X-Router-Session"),
                    force_auto=os.environ.get("ROUTER_FORCE_AUTO") == "1")
                payload, selection = routed.payload, routed.selection
            model_header = selection.get("target_model_id", "")
            tier_header = selection.get("tier", "")
            # Do not forward incoming client authorization, cookies, hosts or arbitrary headers.
            forwarded = {k: self.headers[k] for k in ("anthropic-version", "anthropic-beta",
                                                     "anthropic-workspace-id") if k in self.headers}
            with self.service.provider.open(self.path, payload, headers=forwarded) as upstream:
                content_type = upstream.headers.get("Content-Type", "application/json")
                streaming = bool(payload.get("stream") and self.path == "/v1/messages")
                if streaming:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("X-Router-Model", model_header)
                    self.send_header("X-Router-Tier", tier_header)
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.close_connection = True
                    # readline preserves Anthropic SSE text, tool_use and thinking events unchanged.
                    for line in upstream:
                        self.wfile.write(line)
                        self.wfile.flush()
                else:
                    answer = upstream.read(MAX_BODY_BYTES + 1)
                    if len(answer) > MAX_BODY_BYTES:
                        raise ProviderError("Upstream response too large", 502)
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(answer)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Router-Model", model_header)
                    self.send_header("X-Router-Tier", tier_header)
                    self.end_headers()
                    self.wfile.write(answer)
        except (GatewayInputError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self._json(400, {"error": "invalid_request", "message": str(exc)[:180]})
        except PermissionError:
            self._json(403, {"error": "decision_provider_not_permitted"})
        except ProviderError as exc:
            self._json(exc.status, {"error": "upstream_error", "message": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            return  # client disconnected; never replay requests automatically
        except Exception:
            # Sanitized error; never echo private input or credentials.
            self._json(502, {"error": "gateway_error"})

    def do_OPTIONS(self):
        self._json(405, {"error": "browser_access_not_supported"})


def build_server(host: str = "127.0.0.1", port: int = 8765, *,
                 service: GatewayService | None = None,
                 enable_remote_llm: bool = False, proxy_token: str = "") -> ThreadingHTTPServer:
    # Local development only. Reverse-proxy exposure needs TLS/auth/rate limits and an audit.
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("Experimental gateway may only bind to loopback")
    if not 0 <= port <= 65535:
        raise ValueError("Invalid port")
    instance = service or GatewayService()
    class Handler(GatewayHandler):
        pass
    Handler.service = instance
    Handler.allow_cloud_calls = enable_remote_llm
    Handler.proxy_token = proxy_token
    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description="Local Kev/Jev/OpenAI decision gateway -> Claude Messages API")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--backend", choices=("kev", "jev", "openai"), default="kev")
    parser.add_argument("--kev-url", default="http://127.0.0.1:8009")
    parser.add_argument("--enable-remote-llm", action="store_true",
                        help="Explicitly permit transmitting sanitized logs/code to Claude API")
    parser.add_argument("--allow-hosted-decisions", action="store_true",
                        help="Allow sanitized routing evidence to Jev/OpenAI Decisions")
    args = parser.parse_args()
    if args.backend != "kev" and not args.allow_hosted_decisions:
        parser.error("Hosted decision backend requires --allow-hosted-decisions")
    provider = ClaudeProvider()
    if args.enable_remote_llm and not provider.api_key:
        parser.error("Set ANTHROPIC_API_KEY in environment before enabling paid Claude API calls")
    service = GatewayService(provider=provider, decision_backend=args.backend,
                             kev_base_url=args.kev_url if args.backend == "kev" else None,
                             allow_hosted_decisions=args.allow_hosted_decisions)
    server = build_server(port=args.port, service=service,
                          enable_remote_llm=args.enable_remote_llm,
                          proxy_token=os.environ.get("ROUTER_PROXY_TOKEN", ""))
    print(f"Gateway on http://127.0.0.1:{server.server_port}; "
          f"backend={args.backend}; Claude calls={'enabled' if args.enable_remote_llm else 'disabled'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
