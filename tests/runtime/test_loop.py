import hashlib
import json
import time

import pytest

from knowledge_gap_agent.contracts.config import RunConfig
from knowledge_gap_agent.runtime.models import EvidenceView, ModelReply, TaskInput
from knowledge_gap_agent.runtime.loop import DEFAULT_SYSTEM_PROMPT, run_task


def config(**changes):
    values = dict(experiment_id="fixed-test", variant="e0", model_provider="fixed", model_name="fixed",
                  model_revision="test", temperature=0, max_steps=3, timeout_seconds=1, retry_limit=0,
                  prompt_hash=hashlib.sha256(DEFAULT_SYSTEM_PROMPT.encode()).hexdigest(),
                  toolset_version="1", dataset_version="test", corpus_hash="0" * 64, random_seed=0)
    return RunConfig(**(values | changes))


def evidence(ref="r1", text="资料"):
    return EvidenceView(ref_id=ref, text=text, source_id="source", content_hash=hashlib.sha256(text.encode()).hexdigest())


class FixedModel:
    """固定测试响应，不表示真实模型效果。"""
    def __init__(self, cfg, *actions):
        self.config = cfg
        self.actions = iter(actions)

    def complete(self, system, payload, *, max_tokens=1800):
        value = next(self.actions)
        if isinstance(value, Exception):
            raise value
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return ModelReply(text=text, input_tokens=4, output_tokens=3, model="fixed", raw={"text": text})


def test_research_answer_records_visible_history():
    cfg = config()
    result = run_task(TaskInput(question="问题"), cfg, FixedModel(cfg,
        {"kind": "research", "query": " 查 资料 "},
        {"kind": "answer", "answer": "回答", "citations": ["r1"]}), lambda q: (evidence(),))
    assert result.answer == "回答"
    assert result.stop_reason == "answered"
    assert len(result.events) == 5
    assert result.calls[1].payload["observations"][0]["evidence"][0]["text"] == "资料"
    assert result.calls[0].reply.input_tokens == 4
    assert result.task_id == run_task(TaskInput(question="问题"), cfg, FixedModel(cfg,
        {"kind": "answer", "answer": "答", "citations": []}), lambda q: ()).task_id


@pytest.mark.parametrize("actions,tool,reason", [
    (["not JSON"], lambda q: (), "invalid_action"),
    ([{"kind": "answer", "answer": "答", "citations": ["unknown"]}], lambda q: (), "invalid_citation"),
    ([{"kind": "research", "query": "A  B"}, {"kind": "research", "query": " a b "}], lambda q: (), "repeated_query"),
    ([{"kind": "research", "query": "a"}] * 3, lambda q: (), "repeated_query"),
    ([TimeoutError()], lambda q: (), "model_timeout"),
])
def test_stop_reasons(actions, tool, reason):
    cfg = config()
    result = run_task(TaskInput(question="问题"), cfg, FixedModel(cfg, *actions), tool)
    assert result.stop_reason == reason
    assert result.events[-1].error_type == reason


def test_budget_tool_failure_and_timeout():
    cfg = config(max_steps=1)
    action = {"kind": "research", "query": "a"}
    assert run_task(TaskInput(question="问"), cfg, FixedModel(cfg, action), lambda q: ()).stop_reason == "max_steps"
    def broken(q):
        raise RuntimeError("工具故障")
    assert run_task(TaskInput(question="问"), cfg, FixedModel(cfg, action), broken).stop_reason == "tool_error"
    def slow(q):
        time.sleep(1.1)
        return ()
    assert run_task(TaskInput(question="问"), cfg, FixedModel(cfg, action), slow).stop_reason == "tool_timeout"


def test_prompt_and_client_binding_rejected_before_call():
    cfg = config()
    with pytest.raises(ValueError):
        run_task(TaskInput(question="问"), cfg, FixedModel(cfg), lambda q: (), system_prompt="改动")
    with pytest.raises(ValueError):
        run_task(TaskInput(question="问"), cfg, FixedModel(config(model_name="other")), lambda q: ())


def test_single_json_fence_and_unknown_fields():
    cfg = config()
    result = run_task(TaskInput(question="问"), cfg, FixedModel(cfg,
        '```json\n{"kind":"answer","answer":"答","citations":[]}\n```'), lambda q: ())
    assert result.stop_reason == "answered"
    with pytest.raises(ValueError):
        TaskInput(question="问", labels=["secret"])
    with pytest.raises(ValueError):
        evidence().model_validate(evidence().model_dump() | {"content_hash": "0" * 64})
