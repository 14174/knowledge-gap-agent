from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from knowledge_gap_agent.utils.canonical import sha256_hex


NonEmptyString = Annotated[str, Field(min_length=1)]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
_PLACEHOLDER_SUMMARIES = frozenset({"已修复", "修复", "已处理"})
_TRAILING_SUMMARY_PUNCTUATION = ".,!?;:，。！？；："


def _reject_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


def _require_timezone(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone information")
    return value


def _normalize_summary(value: str) -> str:
    return "".join(value.split()).rstrip(_TRAILING_SUMMARY_PUNCTUATION)


def compute_environment_hash(
    environment_id: str,
    visible_chunk_ids: tuple[str, ...] | list[str],
    research_chunk_ids: tuple[str, ...] | list[str],
    excluded_chunk_ids: tuple[str, ...] | list[str],
) -> str:
    return sha256_hex({
        "environment_id": environment_id,
        "visible_chunk_ids": sorted(visible_chunk_ids),
        "research_chunk_ids": sorted(research_chunk_ids),
        "excluded_chunk_ids": sorted(excluded_chunk_ids),
    })


class KnowledgeEnvironment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    environment_id: NonEmptyString
    visible_chunk_ids: tuple[NonEmptyString, ...]
    research_chunk_ids: tuple[NonEmptyString, ...]
    excluded_chunk_ids: tuple[NonEmptyString, ...]
    environment_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("environment_id")
    @classmethod
    def reject_blank_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("environment_id must not be blank")
        return value

    @field_validator("visible_chunk_ids", "research_chunk_ids", "excluded_chunk_ids")
    @classmethod
    def validate_chunk_ids(cls, values: tuple[str, ...], info: Any) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} must not contain blank strings")
        if len(values) != len(set(values)):
            raise ValueError(f"{info.field_name} must not contain duplicate values")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_disjoint_sets_and_hash(self):
        groups = (set(self.visible_chunk_ids), set(self.research_chunk_ids),
                  set(self.excluded_chunk_ids))
        if any(groups[left] & groups[right] for left, right in ((0, 1), (0, 2), (1, 2))):
            raise ValueError("chunk collections must be pairwise disjoint")
        expected = compute_environment_hash(
            self.environment_id, self.visible_chunk_ids,
            self.research_chunk_ids, self.excluded_chunk_ids,
        )
        if self.environment_hash != expected:
            raise ValueError("environment_hash does not match environment contents")
        return self


class ValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: NonEmptyString
    case_id: NonEmptyString
    message: NonEmptyString
    refs: tuple[NonEmptyString, ...] = ()


class HumanReviewDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISE = "revise"


class HumanReviewRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    case_id: NonEmptyString
    review_target_hash: Sha256Hex
    decision: HumanReviewDecision
    actor: NonEmptyString
    reason: NonEmptyString
    reviewed_at: datetime
    requested_changes: tuple[NonEmptyString, ...] = ()

    @field_validator("case_id", "actor", "reason")
    @classmethod
    def reject_blank_strings(cls, value: str, info: Any) -> str:
        return _reject_blank(value, info.field_name)

    @field_validator("requested_changes")
    @classmethod
    def validate_requested_changes(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("requested_changes must not contain blank strings")
        if len(values) != len(set(values)):
            raise ValueError("requested_changes must not contain duplicate values")
        return values

    @field_validator("reviewed_at")
    @classmethod
    def require_reviewed_at_timezone(cls, value: datetime) -> datetime:
        return _require_timezone(value, "reviewed_at")

    @model_validator(mode="after")
    def require_revise_changes(self):
        if self.decision is HumanReviewDecision.REVISE and not self.requested_changes:
            raise ValueError("requested_changes must not be empty for revise decisions")
        return self


class HumanRevisionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["human_review_revision"] = "human_review_revision"
    case_id: NonEmptyString
    actor: NonEmptyString
    reason: NonEmptyString
    before_review_target_hash: Sha256Hex
    after_review_target_hash: Sha256Hex
    before_summary: NonEmptyString
    after_summary: NonEmptyString
    changed_at: datetime

    @field_validator("case_id", "actor", "reason", "before_summary", "after_summary")
    @classmethod
    def reject_blank_strings(cls, value: str, info: Any) -> str:
        return _reject_blank(value, info.field_name)

    @field_validator("before_summary", "after_summary")
    @classmethod
    def reject_placeholder_summary(cls, value: str, info: Any) -> str:
        if _normalize_summary(value) in _PLACEHOLDER_SUMMARIES:
            raise ValueError(f"{info.field_name} must describe the actual change")
        return value

    @field_validator("changed_at")
    @classmethod
    def require_changed_at_timezone(cls, value: datetime) -> datetime:
        return _require_timezone(value, "changed_at")

    @model_validator(mode="after")
    def require_distinct_target_hashes(self):
        if self.before_review_target_hash == self.after_review_target_hash:
            raise ValueError("before_review_target_hash and after_review_target_hash must differ")
        if _normalize_summary(self.before_summary) == _normalize_summary(
            self.after_summary
        ):
            raise ValueError("before_summary and after_summary must differ")
        return self
