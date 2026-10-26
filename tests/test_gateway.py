import io
import json
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from adaptive_llm_router.gateway.core import (
    AUTO_MODEL, GatewayInputError, GatewayService,
    message_evidence, session_identity, task_from_text,
)
from adaptive_llm_router.gateway.providers import ClaudeProvider
from adaptive_llm_router.gateway.sessions import SessionPins
from adaptive_llm_router.gateway.__main__ import build_server


class FakeResponse(io.BytesIO):
    def __init__(self, body, content_type="application/json"):
        super().__init__(body)
        self.headers = {"Content-Type": content_type}


class FakeProvider:
    api_key = "fake-key-only"
    def __init__(self):
        self.calls = []

    def open(self, path, payload, *, headers=None):
        self.calls.append((path, payload, headers))
        if path == "/v1/messages/count_tokens":
            return FakeResponse(b'{"input_tokens":42}')
        if payload.get("stream"):
            return FakeResponse(
                b'event: message_start\ndata: {"type":"message_start"}\n\n'
                b'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}\n\n',
                "text/event-stream")
        return FakeResponse(json.dumps({
            "type": "message", "model": payload["model"],
            "content": [{"type": "text", "text": "Root cause and verification"}],
            "usage": {"input_tokens": 52, "output_tokens": 17},
            "stop_reason": "end_turn",
        }).encode())


class GatewayCoreTests(unittest.TestCase):
    def setUp(self):
        self.provider = FakeProvider()
        self.calls = []
        def selector(task_type, content, **kwargs):
            self.calls.append((task_type, content))
            return SimpleNamespace(as_dict=lambda: {
                "task_type": task_type, "tier": "l2", "target_model_id": "claude-sonnet-5-5",
                "status": "proposed", "decision_backend": "kev", "uncertain": False
            })
        self.svc = GatewayService(provider=self.provider, selector=selector, pins=SessionPins())

    def test_execute_actual_selected_claude(self):
        answer = self.svc.analyze("log", "Traceback: KeyError\npassword=supersecret")
        self.assertEqual(answer["tier"], "l2")
        self.assertIn("Root cause", answer["analysis"])
        self.assertEqual(answer["usage"]["input_tokens"], 52)
        self.assertNotIn("supersecret", json.dumps(self.provider.calls))
        self.assertEqual(self.provider.calls[0][1]["model"], "claude-sonnet-5-5")

    def test_session_pins_model_through_tool_calls(self):
        first = {"model": "router-auto", "max_tokens": 500,
                 "messages": [{"role": "user", "content": "Investigate a complicated traceback with multiple microservices"}]}
        outcome = self.svc.route_messages(first, session_header="sessionA")
        self.assertEqual(outcome.payload["model"], "claude-sonnet-5-5")
        self.assertEqual(len(self.calls), 1)
        second = {"model": "router-auto", "max_tokens": 500,
                  "messages": [{"role": "user", "content": "tool result output"},
                               {"role": "assistant", "content": [{"type": "tool_use", "id": "t1",
                                                                "name": "Read", "input": {"file_path": "x.py"}}]},
                               {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                                            "content": "actual content"}]}],
                  "tools": [{"name": "Read", "input_schema": {"type": "object"}}]}
        pinned = self.svc.route_messages(second, session_header="sessionA")
        self.assertEqual(pinned.selection["status"], "session_pinned")
        self.assertEqual(pinned.payload["tools"], second["tools"])
        self.assertEqual(pinned.payload["messages"], second["messages"])
        self.assertEqual(len(self.calls), 1)

    def test_continuation_without_session_and_evidence_is_l3(self):
        case = {"model": "router-auto", "messages": [
            {"role": "assistant", "content": "tool_use"},
            {"role": "user", "content": [{"type": "tool_result", "content": "results"}]}]}
        output = self.svc.route_messages(case)
        self.assertEqual(output.selection["tier"], "l3")
        self.assertEqual(output.selection["status"], "unbound_continuation")
        self.assertEqual(len(self.calls), 0)

    def test_manual_model_is_honored_and_allowlisted(self):
        req = {"model": "claude-haiku-5-5", "messages": [{"role": "user", "content": "hi"}]}
        result = self.svc.route_messages(req)
        self.assertEqual(result.selection["status"], "manual")
        self.assertEqual(len(self.calls), 0)
        with self.assertRaises(GatewayInputError):
            self.svc.route_messages({"model": "unapproved", "messages": []})

    def test_helpers_and_invalid_input(self):
        self.assertEqual(task_from_text("Stack TRACE\nError"), "log")
        self.assertEqual(task_from_text("refactor this package"), "code")
        with self.assertRaises(GatewayInputError):
            session_identity("space invalid", "a long original prompt")
        with self.assertRaises(GatewayInputError):
            message_evidence({"messages": "not list"})
        self.assertEqual(self.svc.route_count_tokens({"model": AUTO_MODEL})["model"], "claude-opus-5-5")
        with self.assertRaises(GatewayInputError):
            self.svc.analyze("code", " ", max_tokens=10)

    def test_session_cache_ttl_and_bounding(self):
        pins = SessionPins(ttl_seconds=0.01, capacity=1)
        pins.put("one", {"tier": "l1"})
        pins.put("two", {"tier": "l2"})
        self.assertIsNone(pins.get("one"))
        self.assertEqual(pins.get("two")["tier"], "l2")


class GatewayHTTPTests(unittest.TestCase):
    def setUp(self):
        self.provider = FakeProvider()
        self.svc = GatewayService(
            provider=self.provider,
            selector=lambda task_type, text, **kwargs: SimpleNamespace(
                as_dict=lambda: {"tier": "l2", "target_model_id": "claude-sonnet-5-5",
                                 "status": "proposed", "decision_backend": "kev"}))
        self.server = build_server(port=0, service=self.svc,
                                   enable_remote_llm=True, proxy_token="test-gateway")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def post(self, path, payload, token="test-gateway"):
        request = Request(self.base + path, data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json",
                                   "X-Router-Key": token}, method="POST")
        return urlopen(request, timeout=3)

    def test_gateway_health_and_analyze(self):
        with urlopen(self.base + "/healthz", timeout=3) as response:
            self.assertTrue(json.load(response)["claude_calls_enabled"])
        with self.post("/v1/analyze", {"task_type": "code", "content": "Find this bug"}) as response:
            answer = json.load(response)
        self.assertEqual(answer["model"], "claude-sonnet-5-5")
        self.assertEqual(answer["tier"], "l2")

    def test_messages_nonstream_and_stream_with_tool_payload(self):
        request = {"model": "router-auto", "max_tokens": 512,
                   "messages": [{"role": "user", "content": "Analyze stack trace"}],
                   "tools": [{"name": "Bash", "description": "test", "input_schema": {"type": "object"}}]}
        with self.post("/v1/messages", request) as response:
            self.assertEqual(response.headers["X-Router-Tier"], "l2")
            self.assertEqual(json.load(response)["model"], "claude-sonnet-5-5")
        self.assertEqual(self.provider.calls[-1][1]["tools"], request["tools"])
        request["stream"] = True
        with self.post("/v1/messages", request) as response:
            self.assertEqual(response.headers["Content-Type"], "text/event-stream")
            body = response.read().decode()
        self.assertIn("event: content_block_delta", body)
        self.assertIn('"text":"ok"', body)

    def test_reject_incorrect_auth_and_disabled_cloud(self):
        with self.assertRaises(HTTPError) as error:
            self.post("/v1/messages", {"model": "router-auto"}, token="wrong")
        self.assertEqual(error.exception.code, 401)
        self.server.RequestHandlerClass.allow_cloud_calls = False
        with self.assertRaises(HTTPError) as error:
            self.post("/v1/analyze", {"task_type": "code", "content": "bug"})
        self.assertEqual(error.exception.code, 403)

    def test_count_tokens_without_kev_call(self):
        with self.post("/v1/messages/count_tokens", {
            "model": "router-auto", "messages": [{"role": "user", "content": "test"}]
        }) as response:
            self.assertEqual(json.load(response)["input_tokens"], 42)
        self.assertEqual(self.provider.calls[-1][1]["model"], "claude-opus-5-5")

    def test_remote_binding_rejected(self):
        with self.assertRaises(ValueError):
            build_server(host="0.0.0.0", port=0, service=self.svc)


class ClaudeTransportTests(unittest.TestCase):
    @patch("adaptive_llm_router.gateway.providers.urlopen")
    def test_client_secret_is_not_forwarded(self, urlopen_mock):
        urlopen_mock.return_value = FakeResponse(b"{}")
        provider = ClaudeProvider("upstream-secret")
        provider.open("/v1/messages", {"model": "test", "messages": []},
                      headers={"Authorization": "Bearer client-secret",
                               "x-api-key": "client-api-secret", "anthropic-beta": "test-feature"})
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.get_header("X-api-key"), "upstream-secret")
        self.assertEqual(request.get_header("Anthropic-beta"), "test-feature")
        self.assertNotIn(b"client-secret", request.data)
        with self.assertRaises(ValueError):
            provider.open("/v1/other", {})
        with self.assertRaises(ValueError):
            ClaudeProvider("x", base_url="http://example.org")


if __name__ == "__main__":
    unittest.main()
