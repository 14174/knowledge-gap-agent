import json
from pathlib import Path
import sys

import pytest

from knowledge_gap_agent.runtime.loop import run_task
from knowledge_gap_agent.runtime.models import TaskInput
from knowledge_gap_agent.tracing.store import replay_run, save_run
from knowledge_gap_agent.utils.canonical import sha256_hex
sys.path.insert(0, str(Path(__file__).parents[1] / "runtime"))
from test_loop import FixedModel, config, evidence


def test_save_replay_and_tamper_rejection(tmp_path):
    cfg = config()
    result = run_task(TaskInput(question="问"), cfg, FixedModel(cfg,
        {"kind": "research", "query": "资料"},
        {"kind": "answer", "answer": "答", "citations": ["r1"]}), lambda q: (evidence(),))
    path = save_run(result, tmp_path)
    assert save_run(result, tmp_path) == path
    assert replay_run(path).model_dump(mode="json") == result.model_dump(mode="json")
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["result"]["answer"] = "伪造"
    obj["digest"] = sha256_hex(obj["result"])
    path.write_text(json.dumps(obj), encoding="utf-8")
    with pytest.raises(ValueError):
        replay_run(path)
    with pytest.raises(FileExistsError):
        save_run(result, tmp_path)


@pytest.mark.parametrize("field", ["events", "observations", "calls"])
def test_replay_rejects_rehashed_semantic_tampering(tmp_path, field):
    cfg = config()
    result = run_task(TaskInput(question="问"), cfg, FixedModel(cfg,
        {"kind": "research", "query": "资料"},
        {"kind": "answer", "answer": "答", "citations": ["r1"]}), lambda q: (evidence(),))
    path = save_run(result, tmp_path)
    obj = json.loads(path.read_text(encoding="utf-8"))
    if field == "events":
        obj["result"][field][1]["arguments"]["query"] = "伪造"
    elif field == "observations":
        obj["result"][field][0]["query"] = "伪造"
    else:
        obj["result"][field][0]["payload"]["question"] = "伪造"
    obj["digest"] = sha256_hex(obj["result"])
    path.write_text(json.dumps(obj), encoding="utf-8")
    with pytest.raises(ValueError):
        replay_run(path)


@pytest.mark.parametrize("value", ["invalid", TimeoutError(), {"kind": "research", "query": "a"}])
def test_failure_runs_also_replay(tmp_path, value):
    cfg = config(max_steps=1)
    result = run_task(TaskInput(question="问"), cfg, FixedModel(cfg, value), lambda q: ())
    assert replay_run(save_run(result, tmp_path)).stop_reason == result.stop_reason
