import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from knowledge_gap_agent.contracts.config import RunConfig
from knowledge_gap_agent.contracts.trace import TraceEvent


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class EvidenceView(FrozenModel):
    ref_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_ids: tuple[str, ...] = ()
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def check_hash(self):
        if not self.source_id.strip():
            raise ValueError("来源编号不能为空白")
        if self.source_ids and (self.source_ids[0] != self.source_id
                or len(set(self.source_ids)) != len(self.source_ids)
                or any(not source.strip() for source in self.source_ids)):
            raise ValueError("完整来源须非空、唯一且首项与来源编号一致")
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.content_hash:
            raise ValueError("证据摘要与正文不符")
        return self


class TaskInput(FrozenModel):
    question: str = Field(min_length=1)
    knowledge: tuple[EvidenceView, ...] = ()

    @model_validator(mode="after")
    def unique_refs(self):
        if len({e.ref_id for e in self.knowledge}) != len(self.knowledge):
            raise ValueError("知识引用编号重复")
        return self


class Action(FrozenModel):
    kind: Literal["research", "answer"]
    query: str | None = None
    answer: str | None = None
    citations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def check_fields(self):
        if self.kind == "research":
            if not self.query or not self.query.strip() or self.answer is not None or self.citations:
                raise ValueError("研究动作只接受非空查询")
        elif not self.answer or not self.answer.strip() or self.query is not None:
            raise ValueError("作答动作需要答案且不能包含查询")
        if len(set(self.citations)) != len(self.citations):
            raise ValueError("引用重复")
        return self


class ModelReply(FrozenModel):
    text: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    model: str = Field(min_length=1)
    raw: dict[str, Any]


class ModelAttempt(FrozenModel):
    attempt: int = Field(ge=1)
    latency_ms: int = Field(ge=0)
    raw: dict[str, Any] | None = None
    error_type: str | None = None


class ModelCall(FrozenModel):
    step: int = Field(ge=1)
    system: str
    payload: dict[str, Any]
    reply: ModelReply | None = None
    error_type: str | None = None
    attempts: tuple[ModelAttempt, ...] = ()
    latency_ms: int = Field(ge=0)


class Observation(FrozenModel):
    step: int = Field(ge=1)
    query: str
    evidence: tuple[EvidenceView, ...] = ()
    error_type: str | None = None
    latency_ms: int = Field(ge=0)


class RunResult(FrozenModel):
    run_id: str = Field(pattern=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
    task_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    config: RunConfig
    task: TaskInput
    system_prompt: str
    calls: tuple[ModelCall, ...]
    observations: tuple[Observation, ...]
    events: tuple[TraceEvent, ...]
    answer: str | None = None
    citations: tuple[str, ...] = ()
    stop_reason: str
    latency_ms: int = Field(ge=0)
