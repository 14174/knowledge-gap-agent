import json
from pathlib import Path

from knowledge_gap_agent.runtime.loop import run_task
from knowledge_gap_agent.runtime.model import ModelError
from knowledge_gap_agent.runtime.models import RunResult
from knowledge_gap_agent.utils.canonical import canonical_json, sha256_hex


def save_run(result: RunResult, directory: str | Path) -> Path:
    result = RunResult.model_validate(result.model_dump(mode="python", round_trip=True))
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    data = result.model_dump(mode="json", round_trip=True)
    content = canonical_json({"digest": sha256_hex(data), "result": data}) + "\n"
    path = directory / f"{result.run_id}.json"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except FileExistsError:
        if path.read_text(encoding="utf-8") != content:
            raise FileExistsError("已有同名运行记录且内容不同") from None
    return path


def replay_run(path: str | Path) -> RunResult:
    """使用已记录响应和观察重新运行状态机；绝不访问真实模型或工具。"""
    envelope = json.loads(Path(path).read_text(encoding="utf-8"))
    if set(envelope) != {"digest", "result"} or sha256_hex(envelope["result"]) != envelope["digest"]:
        raise ValueError("运行记录摘要不匹配")
    saved = RunResult.model_validate(envelope["result"])
    if any(e.run_id != saved.run_id for e in saved.events):
        raise ValueError("事件运行身份不匹配")
    calls, observations = iter(saved.calls), iter(saved.observations)

    class RecordedModel:
        config = saved.config
        last_attempts = ()

        def complete(self, system, payload, *, max_tokens=1800):
            call = next(calls)
            self.last_attempts = call.attempts
            if call.reply is None:
                raise ModelError(call.error_type, call.attempts)
            return call.reply

    def recorded_research(query):
        observation = next(observations)
        if query != observation.query:
            raise ValueError("研究查询不匹配")
        if observation.error_type == "tool_timeout":
            raise TimeoutError()
        if observation.error_type:
            raise RuntimeError()
        return observation.evidence

    replayed = run_task(saved.task, saved.config, RecordedModel(), recorded_research, system_prompt=saved.system_prompt)

    def comparable(value):
        # 身份和真实耗时来自原始执行，重放只比较可决定的行为。
        if isinstance(value, dict):
            return {key: comparable(item) for key, item in value.items() if key not in {"run_id", "latency_ms"}}
        if isinstance(value, list):
            return [comparable(item) for item in value]
        return value

    if comparable(replayed.model_dump(mode="json")) != comparable(saved.model_dump(mode="json")):
        raise ValueError("运行记录的动作、事件、观察或最终输出无法重放")
    return saved
