from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class EventType(StrEnum):
    """Trace 事件类型。"""
    RUN_STARTED = "run_started"
    ACTION_SELECTED = "action_selected"
    TOOL_COMPLETED = "tool_completed"
    RUN_FINISHED = "run_finished"


class EventStatus(StrEnum):
    """Trace 事件处理状态。"""
    SUCCESS = "success"
    FAILED = "failed"


class TokenUsage(BaseModel):
    """模型调用令牌用量统计。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    context_tokens: int = Field(default=0, ge=0)

    @computed_field
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class TraceEvent(BaseModel):
    """不可变 Trace 事件；模型字段禁止重新赋值，可变容器由调用方视为只读，深冻结留给存储层复制/序列化。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="1.0", min_length=1)
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    agent: str = Field(min_length=1)
    step: int = Field(ge=0)
    event_type: EventType
    action: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    observation_ref: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: int = Field(default=0, ge=0)
    status: EventStatus
    error_type: str | None = None
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_status_error(self):
        if self.status is EventStatus.FAILED and not self.error_type:
            raise ValueError("failed event requires error_type")
        if self.status is EventStatus.SUCCESS and self.error_type is not None:
            raise ValueError("success event cannot have error_type")
        return self
