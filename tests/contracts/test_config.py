import pytest
from pydantic import ValidationError

from knowledge_gap_agent.contracts.config import ExperimentVariant, RunConfig


def make_config(**overrides):
    data = {
        "experiment_id": "exp-1",
        "variant": "e0",
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


@pytest.mark.parametrize("field", ["schema_version", "experiment_id", "model_provider", "model_name", "model_revision", "toolset_version", "dataset_version"])
def test_run_config_rejects_empty_business_strings(field):
    with pytest.raises(ValidationError):
        RunConfig(**make_config(**{field: ""}))


@pytest.mark.parametrize("field,value", [("temperature", 2.1), ("retry_limit", -1), ("temperature", float("inf")), ("prompt_hash", "z" * 64), ("corpus_hash", "x")])
def test_run_config_rejects_invalid_constraints(field, value):
    with pytest.raises(ValidationError):
        RunConfig(**make_config(**{field: value}))


def test_run_config_rejects_uppercase_variant_and_extra_field():
    with pytest.raises(ValidationError):
        RunConfig(**make_config(variant="E0"))
    with pytest.raises(ValidationError):
        RunConfig(**make_config(extra_field="nope"))


@pytest.mark.parametrize("field,value", [("random_seed", 43), ("temperature", 0.3), ("model_revision", "v2")])
def test_config_hash_changes_when_hash_relevant_field_changes(field, value):
    baseline = RunConfig(**make_config())
    changed = RunConfig(**make_config(**{field: value}))
    assert baseline.config_hash != changed.config_hash
