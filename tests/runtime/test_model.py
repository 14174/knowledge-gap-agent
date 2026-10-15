import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from knowledge_gap_agent.runtime.model import MessagesClient, ModelError
from test_loop import config


@pytest.fixture
def server():
    state = {"requests": [], "responses": []}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            state["requests"].append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            status, body = state["responses"].pop(0)
            time.sleep(state.get("delay", 0))
            self.send_response(status)
            self.end_headers()
            self.wfile.flush()
            time.sleep(state.get("body_delays", [0]).pop(0) if state.get("body_delays") else 0)
            try:
                self.wfile.write(body if isinstance(body, bytes) else json.dumps(body).encode())
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    yield state, f"http://127.0.0.1:{http.server_port}"
    http.shutdown()
    http.server_close()


def response(**changes):
    return {"model": "actual-model", "content": [{"type": "text", "text": "回答"}],
            "usage": {"input_tokens": 11, "output_tokens": 7}, "stop_reason": "end_turn"} | changes


def test_real_http_request_and_usage(server, monkeypatch):
    state, url = server
    monkeypatch.setenv("ANTHROPIC_BASE_URL", url + "/v1")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-secret")
    state["responses"] = [(200, response())]
    client = MessagesClient.from_env(config())
    reply = client.complete("系统", {"question": "问题"})
    assert reply.input_tokens == 11 and reply.model == "actual-model"
    path, request = state["requests"][0]
    assert path == "/v1/messages"
    assert request["max_tokens"] == 1800
    assert request["thinking"] == {"type": "disabled"}
    assert request["model"] == "fixed" and request["temperature"] == 0
    assert client.last_attempts[0].raw == reply.raw


@pytest.mark.parametrize("bad", [response(usage={}), response(stop_reason="max_tokens"), response(content=[])])
def test_invalid_success_rejected(server, bad):
    state, url = server
    state["responses"] = [(200, bad)]
    with pytest.raises(ModelError) as error:
        MessagesClient(config(), url, "secret").complete("系统", {})
    assert error.value.attempts[0].raw == bad
    assert "secret" not in str(error.value) and url not in str(error.value)


def test_retries_record_server_error_then_success(server):
    state, url = server
    state["responses"] = [(500, {"error": {"type": "busy"}}), (200, response())]
    attempts = []
    client = MessagesClient(config(retry_limit=1), url, "secret", before_attempt=lambda: attempts.append(1))
    client.complete("系统", {})
    assert len(client.last_attempts) == 2
    assert client.last_attempts[0].raw == {"error": {"type": "busy"}}
    assert attempts == [1, 1]


def test_before_attempt_can_reject_without_network(server):
    state, url = server
    def reject():
        raise RuntimeError("预算耗尽")
    with pytest.raises(RuntimeError, match="预算耗尽"):
        MessagesClient(config(), url, "secret", before_attempt=reject).complete("系统", {})
    assert state["requests"] == []


def test_real_http_timeout_is_enforced(server):
    state, url = server
    state["responses"] = [(200, response())]
    state["delay"] = 1.2
    tick = time.monotonic()
    with pytest.raises(ModelError) as error:
        MessagesClient(config(), url, "secret").complete("系统", {})
    assert error.value.error_type == "model_timeout"
    assert time.monotonic() - tick < 1.15
    assert error.value.attempts[0].raw is None


@pytest.mark.parametrize("body", [[], "错误响应", None])
def test_non_object_success_is_archived_as_invalid_response(server, body):
    state, url = server
    state["responses"] = [(200, body)]
    client = MessagesClient(config(), url, "secret")
    with pytest.raises(ModelError) as error:
        client.complete("系统", {})
    assert error.value.error_type == "invalid_response"
    assert error.value.attempts[0].raw == {"response": body}
    assert client.last_attempts == error.value.attempts


def test_error_body_timeout_is_archived_and_retried(server):
    state, url = server
    state["responses"] = [(502, {"error": "busy"}), (200, response())]
    state["body_delays"] = [1.2, 0]
    client = MessagesClient(config(retry_limit=1), url, "secret")
    assert client.complete("系统", {}).input_tokens == 11
    assert len(state["requests"]) == 2
    assert len(client.last_attempts) == 2
    assert client.last_attempts[0].error_type == "model_timeout"
    assert client.last_attempts[0].raw is None


def test_plain_text_error_body_is_preserved(server):
    state, url = server
    state["responses"] = [(502, b"upstream unavailable")]
    client = MessagesClient(config(), url, "secret")
    with pytest.raises(ModelError) as error:
        client.complete("系统", {})
    assert error.value.attempts[0].raw == {"response_text": "upstream unavailable"}
    assert str(error.value) == "http_error"


def test_before_retry_rejection_keeps_previous_attempt(server):
    state, url = server
    state["responses"] = [(502, {"error": "busy"})]
    calls = []
    def gate():
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("预算耗尽")
    client = MessagesClient(config(retry_limit=1), url, "secret", before_attempt=gate)
    with pytest.raises(RuntimeError, match="预算耗尽"):
        client.complete("系统", {})
    assert len(state["requests"]) == 1
    assert len(client.last_attempts) == 1
    assert client.last_attempts[0].raw == {"error": "busy"}
