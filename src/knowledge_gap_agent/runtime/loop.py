import hashlib
import json
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Callable
from uuid import uuid4

from knowledge_gap_agent.contracts.config import RunConfig
from knowledge_gap_agent.contracts.trace import EventStatus, EventType, TokenUsage, TraceEvent
from knowledge_gap_agent.runtime.model import ModelClient
from knowledge_gap_agent.runtime.models import Action, EvidenceView, ModelCall, ModelReply, Observation, RunResult, TaskInput
from knowledge_gap_agent.utils.canonical import sha256_hex

DEFAULT_SYSTEM_PROMPT = '''你是证据驱动的问答助手。输入包含问题、可见知识、动作历史和研究观察。
仅输出一个 JSON 对象。需要资料时输出 {"kind":"research","query":"具体查询"}；
可以作答时输出 {"kind":"answer","answer":"答案","citations":["可见引用编号"]}。
不得引用输入中不存在的编号。证据不足时明确说明。'''


def parse_action(text: str) -> Action:
    text = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    return Action.model_validate(json.loads(text))


def normalized_query(query: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", query).casefold().split())


def make_payload(task: TaskInput, actions: list[Action], observations: list[Observation]) -> dict:
    return {"question": task.question, "knowledge": [e.model_dump(mode="json") for e in task.knowledge],
            "actions": [a.model_dump(mode="json") for a in actions],
            "observations": [o.model_dump(mode="json") for o in observations]}


def run_task(task: TaskInput, config: RunConfig, model: ModelClient,
             research: Callable[[str], tuple[EvidenceView, ...]], *, system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> RunResult:
    task = TaskInput.model_validate(task.model_dump(mode="python"))
    config = RunConfig.model_validate(config.model_dump(mode="python"))
    if hashlib.sha256(system_prompt.encode("utf-8")).hexdigest() != config.prompt_hash:
        raise ValueError("系统提示词摘要不匹配")
    if model.config != config:
        raise ValueError("模型客户端配置不匹配")
    started = time.monotonic()
    run_id, task_id = str(uuid4()), sha256_hex(task.model_dump(mode="json"))
    events, calls, observations, actions = [], [], [], []
    seen, visible = set(), {e.ref_id: e for e in task.knowledge}
    answer, citations, reason = None, (), "max_steps"

    def emit(kind: EventType, step: int, *, action: str | None = None, arguments: dict | None = None,
             observation_ref: str | None = None, usage: TokenUsage | None = None,
             error: str | None = None, latency: int = 0) -> None:
        events.append(TraceEvent(run_id=run_id, task_id=task_id, agent="runtime", step=step,
            event_type=kind, action=action, arguments=arguments or {}, observation_ref=observation_ref,
            usage=usage or TokenUsage(), latency_ms=latency, status=EventStatus.FAILED if error else EventStatus.SUCCESS,
            error_type=error, config_hash=config.config_hash))

    emit(EventType.RUN_STARTED, 0)
    for step in range(1, config.max_steps + 1):
        payload = make_payload(task, actions, observations)
        tick = time.monotonic()
        try:
            reply = model.complete(system_prompt, payload, max_tokens=1800)
            reply = ModelReply.model_validate(reply.model_dump(mode="python"))
        except Exception as exc:
            reason = "model_timeout" if isinstance(exc, TimeoutError) or getattr(exc, "error_type", "") == "model_timeout" else "model_error"
            calls.append(ModelCall(step=step, system=system_prompt, payload=payload, error_type=reason,
                attempts=getattr(exc, "attempts", getattr(model, "last_attempts", ())),
                latency_ms=int((time.monotonic()-tick)*1000)))
            break
        latency = int((time.monotonic()-tick)*1000)
        calls.append(ModelCall(step=step, system=system_prompt, payload=payload, reply=reply,
            attempts=tuple(getattr(model, "last_attempts", ())), latency_ms=latency))
        try:
            action = parse_action(reply.text)
        except (ValueError, TypeError):
            reason = "invalid_action"
            break
        actions.append(action)
        emit(EventType.ACTION_SELECTED, step, action=action.kind, arguments=action.model_dump(mode="json"),
             usage=TokenUsage(input_tokens=reply.input_tokens, output_tokens=reply.output_tokens), latency=latency)
        if action.kind == "answer":
            if not set(action.citations) <= visible.keys():
                reason = "invalid_citation"
            else:
                answer, citations, reason = action.answer, action.citations, "answered"
            break
        query = normalized_query(action.query)
        if query in seen:
            reason = "repeated_query"
            break
        seen.add(query)
        tick = time.monotonic()
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(research, action.query)
        evidence, error = (), None
        try:
            returned = future.result(timeout=config.timeout_seconds)
            evidence = tuple(EvidenceView.model_validate(e.model_dump(mode="python")) for e in returned)
            refs = [e.ref_id for e in evidence]
            if len(set(refs)) != len(refs) or any(e.ref_id in visible and visible[e.ref_id] != e for e in evidence):
                raise ValueError("工具证据引用冲突")
        except FutureTimeout:
            error = "tool_timeout"
        except Exception:
            error = "tool_error"
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        observation = Observation(step=step, query=action.query, evidence=evidence if not error else (),
            error_type=error, latency_ms=int((time.monotonic()-tick)*1000))
        observations.append(observation)
        emit(EventType.TOOL_COMPLETED, step, action="research", arguments={"query": action.query},
             observation_ref=f"observation-{len(observations)}", error=error, latency=observation.latency_ms)
        if error:
            reason = error
            break
        visible.update({e.ref_id: e for e in evidence})
    emit(EventType.RUN_FINISHED, len(calls), arguments={"stop_reason": reason, "answer": answer, "citations": list(citations)},
         error=None if reason == "answered" else reason)
    return RunResult(run_id=run_id, task_id=task_id, config=config, task=task, system_prompt=system_prompt,
        calls=tuple(calls), observations=tuple(observations), events=tuple(events), answer=answer,
        citations=citations, stop_reason=reason, latency_ms=int((time.monotonic()-started)*1000))
