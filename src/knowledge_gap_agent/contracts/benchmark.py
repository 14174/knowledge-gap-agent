from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CaseCategory(StrEnum):
    """基准样例的本地知识缺口分类。"""
    LOCAL_SUFFICIENT = "local_sufficient"
    LOCAL_PARTIAL = "local_partial"
    LOCAL_MISSING = "local_missing"
    OUTDATED = "outdated"
    CONFLICT = "conflict"
    REPEATED_KNOWLEDGE = "repeated_knowledge"


class DraftStatus(StrEnum):
    GENERATED = "generated"
    VALIDATED = "validated"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REVISE = "revise"
    REJECTED = "rejected"


class HumanReviewStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class BenchmarkCase(BaseModel):
    """不可变基准样例；集合字段在模型内部统一冻结为元组。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    case_id: str = Field(min_length=1)
    base_question_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    category: CaseCategory
    annotation_reason: str = Field(min_length=1)
    required_claims: tuple[Annotated[str, Field(min_length=1)], ...] = Field(min_length=1)
    allowed_source_ids: tuple[Annotated[str, Field(min_length=1)], ...] = Field(min_length=1)
    answer_key: tuple[Annotated[str, Field(min_length=1)], ...] = Field(min_length=1)
    local_knowledge_ids: tuple[Annotated[str, Field(min_length=1)], ...]
    need_research: bool
    environment_id: str = Field(min_length=1)
    required_claim_ids: tuple[Annotated[str, Field(min_length=1)], ...] = Field(min_length=1)
    missing_claim_ids: tuple[Annotated[str, Field(min_length=1)], ...]
    evidence_chunk_ids: tuple[Annotated[str, Field(min_length=1)], ...] = Field(min_length=1)
    draft_status: DraftStatus
    review_status: ReviewStatus
    human_review_status: HumanReviewStatus

    @field_validator(
        "case_id", "base_question_id", "question", "annotation_reason", "environment_id"
    )
    @classmethod
    def reject_blank_strings(cls, value: str, info: Any) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator(
        "required_claims", "allowed_source_ids", "answer_key", "local_knowledge_ids",
        "required_claim_ids", "missing_claim_ids", "evidence_chunk_ids",
    )
    @classmethod
    def validate_collections(cls, values: tuple[str, ...], info: Any) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} must not contain blank strings")
        if len(values) != len(set(values)):
            raise ValueError(f"{info.field_name} must not contain duplicate values")
        return values

    @model_validator(mode="after")
    def validate_research_need(self):
        if not set(self.missing_claim_ids).issubset(self.required_claim_ids):
            raise ValueError("missing_claim_ids must be a subset of required_claim_ids")
        if self.category is CaseCategory.LOCAL_SUFFICIENT and self.need_research:
            raise ValueError(f"category {self.category.value} cannot need research")
        if self.category in {CaseCategory.LOCAL_PARTIAL, CaseCategory.LOCAL_MISSING,
                             CaseCategory.OUTDATED, CaseCategory.CONFLICT} and not self.need_research:
            raise ValueError(f"category {self.category.value} requires research")
        return self
