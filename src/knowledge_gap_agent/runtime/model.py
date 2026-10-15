import json
import os
import socket
import time
import urllib.error
import urllib.request
from typing import Callable, Protocol

from knowledge_gap_agent.contracts.config import RunConfig
from knowledge_gap_agent.runtime.models import ModelAttempt, ModelReply
from knowledge_gap_agent.utils.canonical import canonical_json


def _response_body(response) -> dict:
    """保持字典记录契约，同时区分非对象 JSON、原文和未读到正文。"""
    text = response.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(text)
    except ValueError:
        return {"response_text": text}
    return parsed if isinstance(parsed, dict) else {"response": parsed}


class ModelClient(Protocol):
    config: RunConfig

    def complete(self, system: str, payload: dict, *, max_tokens: int = 1800) -> ModelReply: ...


class ModelError(RuntimeError):
    def __init__(self, error_type: str, attempts=()):
        super().__init__(error_type)
        self.error_type = error_type
        self.attempts = tuple(attempts)


class MessagesClient:
    """兼容消息接口；错误只输出类型，不回显地址或鉴权信息。"""

    def __init__(self, config: RunConfig, base_url: str, token: str, *, before_attempt: Callable[[], None] | None = None):
        self.config = RunConfig.model_validate(config.model_dump(mode="python"))
        self._url = base_url.rstrip("/") + ("/messages" if base_url.rstrip("/").endswith("/v1") else "/v1/messages")
        self._token = token
        self._before_attempt = before_attempt
        self.last_attempts: tuple[ModelAttempt, ...] = ()

    @classmethod
    def from_env(cls, config, *, before_attempt=None):
        base, token = os.environ.get("ANTHROPIC_BASE_URL"), os.environ.get("ANTHROPIC_AUTH_TOKEN")
        if not base or not token:
            raise ValueError("缺少模型接口环境配置")
        return cls(config, base, token, before_attempt=before_attempt)

    def complete(self, system: str, payload: dict, *, max_tokens=1800) -> ModelReply:
        body = canonical_json({"model": self.config.model_name, "temperature": self.config.temperature,
            "max_tokens": max_tokens, "system": system, "thinking": {"type": "disabled"},
            "messages": [{"role": "user", "content": canonical_json(payload)}]}).encode("utf-8")
        attempts = []
        self.last_attempts = ()
        for number in range(1, self.config.retry_limit + 2):
            if self._before_attempt is not None:
                self._before_attempt()
            tick, raw, retryable = time.monotonic(), None, False
            try:
                request = urllib.request.Request(self._url, data=body, headers={
                    "Content-Type": "application/json", "Authorization": "Bearer " + self._token,
                    "anthropic-version": "2023-06-01"}, method="POST")
                try:
                    with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                        raw = _response_body(response)
                except urllib.error.HTTPError as exc:
                    error = "http_error"
                    retryable = exc.code == 429 or exc.code >= 500
                    with exc:
                        raw = _response_body(exc)
                else:
                    if raw.get("stop_reason") != "end_turn":
                        raise ValueError("响应未正常完成")
                    text = "".join(block["text"] for block in raw.get("content", []) if block.get("type") == "text")
                    usage = raw["usage"]
                    # 不允许把缺失用量或布尔值当作成功的零用量。
                    if any(type(usage.get(k)) is not int for k in ("input_tokens", "output_tokens")):
                        raise ValueError("响应缺少真实用量")
                    reply = ModelReply(text=text, input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
                        model=raw["model"], raw=raw)
                    attempts.append(ModelAttempt(attempt=number, latency_ms=int((time.monotonic()-tick)*1000), raw=raw))
                    self.last_attempts = tuple(attempts)
                    return reply
            except (TimeoutError, socket.timeout):
                error, retryable = "model_timeout", True
            except urllib.error.URLError as exc:
                error = "model_timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "transport_error"
                retryable = True
            except (ValueError, KeyError, TypeError, AttributeError):
                error = "invalid_response"
            attempts.append(ModelAttempt(attempt=number, latency_ms=int((time.monotonic()-tick)*1000), raw=raw, error_type=error))
            self.last_attempts = tuple(attempts)
            if not retryable or number > self.config.retry_limit:
                raise ModelError(error, attempts) from None
        raise AssertionError("不可达分支")
