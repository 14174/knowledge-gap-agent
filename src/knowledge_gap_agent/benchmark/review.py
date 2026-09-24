from datetime import datetime
from enum import StrEnum
import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from knowledge_gap_agent.contracts.benchmark import (
    BenchmarkCase,
    CaseCategory,
    HumanReviewStatus,
    ReviewStatus,
)


NonEmptyString = Annotated[str, Field(min_length=1)]


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"


class ReviewRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    case_id: NonEmptyString
    decision: ReviewDecision
    issues: tuple[NonEmptyString, ...]
    suggested_changes: tuple[NonEmptyString, ...]
    evidence_refs: tuple[NonEmptyString, ...] = Field(min_length=1)
    reviewer_confidence: float
    labeler_reasoning_seen: Literal[False] = False
    prior_rule_failure_count: int
    prompt_version: NonEmptyString
    prompt_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    model_provider: NonEmptyString
    model_name: NonEmptyString
    model_revision: NonEmptyString
    reviewed_at: datetime

    @field_validator(
        "case_id", "prompt_version", "model_provider", "model_name", "model_revision"
    )
    @classmethod
    def reject_blank_strings(cls, value: str, info: Any) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("issues", "suggested_changes", "evidence_refs")
    @classmethod
    def validate_collections(cls, values: tuple[str, ...], info: Any) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} must not contain blank strings")
        if len(values) != len(set(values)):
            raise ValueError(f"{info.field_name} must not contain duplicate values")
        return values

    @field_validator("reviewer_confidence", mode="before")
    @classmethod
    def validate_confidence(cls, value: object) -> object:
        if type(value) is not float:
            raise ValueError("reviewer_confidence must be a finite float between 0 and 1")
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("reviewer_confidence must be a finite float between 0 and 1")
        return value

    @field_validator("prior_rule_failure_count", mode="before")
    @classmethod
    def validate_prior_rule_failure_count(cls, value: object) -> object:
        if type(value) is not int or value < 0:
            raise ValueError("prior_rule_failure_count must be a nonnegative integer")
        return value

    @field_validator("reviewed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reviewed_at must include timezone information")
        return value

    @model_validator(mode="after")
    def validate_decision_details(self):
        if self.decision in {ReviewDecision.REVISE, ReviewDecision.REJECT} and not self.issues:
            raise ValueError("issues must not be empty for revise or reject decisions")
        if self.decision is ReviewDecision.REVISE and not self.suggested_changes:
            raise ValueError("suggested_changes must not be empty for revise decisions")
        return self


def _revalidate_inputs(
    case: BenchmarkCase, review: ReviewRecord
) -> tuple[BenchmarkCase, ReviewRecord]:
    validated_case = BenchmarkCase.model_validate(case.model_dump(mode="python"))
    validated_review = ReviewRecord.model_validate(review.model_dump(mode="python"))
    return validated_case, validated_review


def _validate_case_link(case: BenchmarkCase, review: ReviewRecord) -> None:
    if case.case_id != review.case_id:
        raise ValueError(
            f"case_id mismatch: case={case.case_id!r}, review={review.case_id!r}"
        )


def requires_human_review(case: BenchmarkCase, review: ReviewRecord) -> bool:
    case, review = _revalidate_inputs(case, review)
    _validate_case_link(case, review)
    return (
        case.category in {CaseCategory.OUTDATED, CaseCategory.CONFLICT}
        or review.decision in {ReviewDecision.REVISE, ReviewDecision.REJECT}
        or review.reviewer_confidence < 0.8
        or review.prior_rule_failure_count > 0
    )


def apply_review_gate(case: BenchmarkCase, review: ReviewRecord) -> BenchmarkCase:
    case, review = _revalidate_inputs(case, review)
    _validate_case_link(case, review)
    if case.draft_status.value != "validated":
        raise ValueError(
            f"case_id={case.case_id}: current draft_status={case.draft_status.value}; "
            "required draft_status=validated"
        )
    if case.review_status is not ReviewStatus.PENDING:
        raise ValueError(
            f"case_id={case.case_id}: current review_status={case.review_status.value}; "
            "required review_status=pending"
        )
    unknown_refs = set(review.evidence_refs).difference(case.evidence_chunk_ids)
    if unknown_refs:
        raise ValueError(
            f"case_id={case.case_id}: evidence_refs contain unknown refs: "
            f"{sorted(unknown_refs)!r}"
        )
    if case.human_review_status in {
        HumanReviewStatus.APPROVED,
        HumanReviewStatus.REJECTED,
    }:
        raise ValueError(
            f"case_id={case.case_id}: current human_review_status="
            f"{case.human_review_status.value} is final; required non-final human_review_status"
        )

    review_status = {
        ReviewDecision.APPROVE: ReviewStatus.APPROVED,
        ReviewDecision.REVISE: ReviewStatus.REVISE,
        ReviewDecision.REJECT: ReviewStatus.REJECTED,
    }[review.decision]
    human_status = (
        HumanReviewStatus.PENDING
        if requires_human_review(case, review)
        else HumanReviewStatus.NOT_REQUIRED
    )
    return case.model_copy(update={
        "review_status": review_status,
        "human_review_status": human_status,
    })
