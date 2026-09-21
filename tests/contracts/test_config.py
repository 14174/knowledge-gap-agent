import pytest
from pydantic import ValidationError

from knowledge_gap_agent.contracts.config import ExperimentVariant, RunConfig


def make_config(**overrides):
    data = {
        "experiment_id": "exp-1",
        "variant": "E0",
        "model_provider": "openai",
        "model_name": "gpt-test",
        "model_revision": "v1",
        "temperature": 0.2,
        "max_steps": 3,
        "timeout_seconds": 30,
        "retry_limit": 1,
        "prompt_hash": "a" * 64,
        "toolset_version": "1",
        "dataset_version": "1",
        "corpus_hash": "b" * 64,
        "random_seed": 42,
    }
    data.update(overrides)
    return data


def test_run_config_hash_is_stable_and_instance_is_frozen():
    config = RunConfig(**make_config())
    assert config.variant is ExperimentVariant.E0
    assert config.config_hash == RunConfig(**make_config()).config_hash
    with pytest.raises(ValidationError):
        config.max_steps = 4


@pytest.mark.parametrize("field,value", [("temperature", float("nan")), ("max_steps", 0), ("timeout_seconds", 0)])
def test_run_config_rejects_invalid_values(field, value):
    with pytest.raises(ValidationError):
        RunConfig(**make_config(**{field: value}))
