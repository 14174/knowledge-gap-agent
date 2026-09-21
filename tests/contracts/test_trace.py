import pytest
from pydantic import ValidationError

from knowledge_gap_agent.contracts.trace import EventStatus, EventType, TokenUsage, TraceEvent


def event(**overrides):
    data = dict(run_id="r1", task_id="t1", agent="a1", step=0, event_type=EventType.RUN_STARTED,
                status=EventStatus.SUCCESS, config_hash="a" * 64)
    data.update(overrides)
    return TraceEvent(**data)


def test_trace_json_serializes_enum_and_total_tokens():
    usage = TokenUsage(input_tokens=3, output_tokens=4, context_tokens=2)
    assert usage.model_dump(mode="json")["total_tokens"] == 7
    item = event(usage=usage)
    assert item.usage.total_tokens == 7
    assert '"event_type":"run_started"' in item.model_dump_json()
    assert item.model_dump(mode="json")["usage"]["total_tokens"] == 7


def test_failed_requires_error_type_and_success_forbids_it():
    with pytest.raises(ValidationError):
        event(status=EventStatus.FAILED)
    with pytest.raises(ValidationError):
        event(error_type="Oops")


@pytest.mark.parametrize("agent", [None, ""])
def test_trace_requires_non_empty_agent(agent):
    values = {"agent": agent}
    if agent is None:
        values = {"agent": None}
    with pytest.raises(ValidationError):
        event(**values)


@pytest.mark.parametrize("field,value", [("step", -1), ("latency_ms", -1)])
def test_trace_rejects_negative_values(field, value):
    with pytest.raises(ValidationError):
        event(**{field: value})


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "context_tokens"])
def test_token_usage_rejects_negative_values(field):
    with pytest.raises(ValidationError):
        TokenUsage(**{field: -1})


def test_trace_rejects_extra_fields():
    with pytest.raises(ValidationError):
        event(unknown=1)


@pytest.mark.parametrize("config_hash", ["A" * 64, "a" * 63, "g" * 64])
def test_trace_rejects_invalid_config_hash(config_hash):
    with pytest.raises(ValidationError):
        event(config_hash=config_hash)


def test_trace_is_frozen():
    item = event()
    with pytest.raises(ValidationError):
        item.step = 1
