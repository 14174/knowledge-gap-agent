import time
from pathlib import Path

from .io import write_once


class RecordedClient:
    """统一捕获运行、门禁、提取、验证及裁判的真实调用与重试。"""
    def __init__(self, client, directory):
        self.client, self.config, self.directory = client, client.config, Path(directory)
        self.records = []
        self.component = "runtime"
        self._offset = len(list(self.directory.glob("call-*.json")))

    @property
    def last_attempts(self):
        return tuple(getattr(self.client, "last_attempts", ()))

    def complete(self, system, payload, *, max_tokens=1800):
        tick = time.monotonic()
        reply, error = None, None
        try:
            reply = self.client.complete(system, payload, max_tokens=min(max_tokens, 1800))
            return reply
        except Exception as exc:
            error = getattr(exc, "error_type", type(exc).__name__)
            raise
        finally:
            attempts = [attempt.model_dump(mode="json") for attempt in self.last_attempts]
            # 每次HTTP尝试都有独立用量；重试失败也必须保留已知服务用量。
            usages = [attempt.get("raw", {}).get("usage") if isinstance(attempt.get("raw"), dict) else None for attempt in attempts]
            if not attempts and reply is not None:
                usages = [{"input_tokens": reply.input_tokens, "output_tokens": reply.output_tokens}]
            known = bool(usages) and all(isinstance(usage, dict) and type(usage.get("input_tokens")) is int and type(usage.get("output_tokens")) is int for usage in usages)
            record = {"component": self.component, "system": system, "payload": payload,
                      "reply": reply.model_dump(mode="json") if reply else None,
                      "attempts": attempts, "error_type": error,
                      "input_tokens": sum(u["input_tokens"] for u in usages) if known else None,
                      "output_tokens": sum(u["output_tokens"] for u in usages) if known else None,
                      "known_input_tokens": sum(u.get("input_tokens", 0) for u in usages if isinstance(u, dict) and type(u.get("input_tokens")) is int),
                      "known_output_tokens": sum(u.get("output_tokens", 0) for u in usages if isinstance(u, dict) and type(u.get("output_tokens")) is int),
                      "usage_complete": known, "latency_ms": int((time.monotonic() - tick) * 1000)}
            self.records.append(record)
            write_once(self.directory / f"call-{self._offset + len(self.records):03d}.json", record)


def total_usage(records):
    return {"input_tokens": sum(r["input_tokens"] for r in records) if all(r["input_tokens"] is not None for r in records) else None,
            "output_tokens": sum(r["output_tokens"] for r in records) if all(r["output_tokens"] is not None for r in records) else None,
            "known_input_tokens": sum(r.get("known_input_tokens", 0) for r in records),
            "known_output_tokens": sum(r.get("known_output_tokens", 0) for r in records),
            "model_latency_ms": sum(r["latency_ms"] for r in records), "calls": len(records)}
