"""展示稳定配置哈希、规范 JSON Trace 和失败校验。"""

from pydantic import ValidationError

from knowledge_gap_agent.contracts.config import ExperimentVariant, RunConfig
from knowledge_gap_agent.contracts.trace import EventStatus, EventType, TraceEvent


def build_config() -> RunConfig:
    return RunConfig(
        experiment_id="day1-contract",
        variant=ExperimentVariant.E0,
        model_provider="openai-compatible",
        model_name="test-model",
        model_revision="2026-09-21",
        temperature=0.0,
        max_steps=8,
        timeout_seconds=60,
        retry_limit=1,
        prompt_hash="a" * 64,
        toolset_version="v1",
        dataset_version="v0.1",
        corpus_hash="b" * 64,
        random_seed=7,
    )


def main() -> None:
    config = build_config()
    reordered = RunConfig(**dict(reversed(list(config.model_dump().items()))))
    print(f"config_hash={config.config_hash}")
    print(f"hash_stable={config.config_hash == reordered.config_hash}")

    event = TraceEvent(
        run_id="run-demo-001", task_id="task-demo-001", step=0,
        agent="researcher", event_type=EventType.RUN_STARTED,
        latency_ms=0, status=EventStatus.SUCCESS, config_hash=config.config_hash,
    )
    print(event.model_dump_json(indent=2))

    try:
        TraceEvent(
            run_id="run-demo-002", task_id="task-demo-001", step=1,
            agent="researcher", event_type=EventType.TOOL_COMPLETED,
            latency_ms=12, status=EventStatus.FAILED, config_hash=config.config_hash,
        )
    except ValidationError as exc:
        print(f"invalid_trace_rejected={exc.error_count() > 0}")


if __name__ == "__main__":
    main()
