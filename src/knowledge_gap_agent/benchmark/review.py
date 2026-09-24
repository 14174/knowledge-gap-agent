from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from knowledge_gap_agent.contracts.benchmark import (
    BenchmarkCase,
    CaseCategory,
    DraftStatus,
    HumanReviewStatus,
    ReviewStatus,
)
from knowledge_gap_agent.benchmark.models import KnowledgeEnvironment
from knowledge_gap_agent.corpus.models import Claim, CorpusChunk
from knowledge_gap_agent.utils.canonical import sha256_hex


NonEmptyString = Annotated[str, Field(min_length=1)]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

REVIEW_CASE_INCLUDED_FIELDS = frozenset({
    "schema_version", "case_id", "base_question_id", "question", "category",
    "required_claims", "allowed_source_ids", "answer_key", "local_knowledge_ids",
    "need_research", "environment_id", "required_claim_ids", "missing_claim_ids",
    "evidence_chunk_ids", "draft_status",
})
REVIEW_CASE_EXCLUDED_FIELDS = frozenset({
    "annotation_reason", "review_status", "human_review_status",
})
KNOWLEDGE_ENVIRONMENT_FIELDS = frozenset({
    "environment_id", "visible_chunk_ids", "research_chunk_ids",
    "excluded_chunk_ids", "environment_hash",
})
REVIEW_ENVIRONMENT_FIELDS = frozenset({
    "environment_id", "environment_hash", "visible_chunks", "research_chunks",
    "excluded_chunks",
})
REVIEW_CHUNK_INCLUDED_FIELDS = frozenset({
    "chunk_id", "source_id", "heading_path", "text", "claim_ids",
})
REVIEW_CHUNK_EXCLUDED_FIELDS = frozenset({
    "start_line", "end_line", "token_terms", "content_hash",
})
REVIEW_CLAIM_FIELDS = frozenset({
    "claim_id", "statement", "evidence_chunk_ids", "valid_from", "valid_until",
    "conflicts_with",
})
REVIEW_TARGET_FIELDS = frozenset({"schema_version", "case", "environment", "claims"})


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"


class ReviewCaseInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["2.0"]
    case_id: NonEmptyString
    base_question_id: NonEmptyString
    question: NonEmptyString
    category: CaseCategory
    required_claims: tuple[NonEmptyString, ...]
    allowed_source_ids: tuple[NonEmptyString, ...]
    answer_key: tuple[NonEmptyString, ...]
    local_knowledge_ids: tuple[NonEmptyString, ...]
    need_research: bool
    environment_id: NonEmptyString
    required_claim_ids: tuple[NonEmptyString, ...]
    missing_claim_ids: tuple[NonEmptyString, ...]
    evidence_chunk_ids: tuple[NonEmptyString, ...]
    draft_status: DraftStatus


class ReviewChunkInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: NonEmptyString
    source_id: NonEmptyString
    heading_path: tuple[NonEmptyString, ...]
    text: NonEmptyString
    claim_ids: tuple[NonEmptyString, ...]


class ReviewClaimInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: NonEmptyString
    statement: NonEmptyString
    evidence_chunk_ids: tuple[NonEmptyString, ...]
    valid_from: datetime | None
    valid_until: datetime | None
    conflicts_with: tuple[NonEmptyString, ...]


class ReviewEnvironmentInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    environment_id: NonEmptyString
    environment_hash: Sha256Hex
    visible_chunks: tuple[ReviewChunkInput, ...]
    research_chunks: tuple[ReviewChunkInput, ...]
    excluded_chunks: tuple[ReviewChunkInput, ...]


class ReviewTargetInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    case: ReviewCaseInput
    environment: ReviewEnvironmentInput
    claims: tuple[ReviewClaimInput, ...]


def _review_target_hash(value: ReviewTargetInput) -> str:
    target = ReviewTargetInput.model_validate(
        value.model_dump(mode="python", exclude={"review_target_hash"})
    )
    return sha256_hex(target.model_dump(mode="json"))


class ReviewInput(ReviewTargetInput):
    review_target_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_review_target_hash(self):
        if self.review_target_hash != _review_target_hash(self):
            raise ValueError(
                "review_target_hash does not match Reviewer-visible input"
            )
        return self


class ReviewRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    case_id: NonEmptyString
    review_target_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
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


class ReviewRevisionRecord(BaseModel):
    """候选问题在复核后修订的最小、非人工审计记录。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    base_question_id: NonEmptyString
    actor: Literal["independent_reviewer_and_quality_audit"]
    trigger: Literal["round_1_review_revision"]
    human_approved: Literal[False] = False
    before_question: NonEmptyString
    after_question: NonEmptyString
    affected_case_ids: tuple[NonEmptyString, ...] = Field(min_length=1)
    reviewer_revise_case_ids: tuple[NonEmptyString, ...] = Field(min_length=1)
    quality_audit_case_ids: tuple[NonEmptyString, ...] = Field(min_length=1)
    reason: NonEmptyString
    changed_at: datetime
    round1_inputs_hash: Sha256Hex
    round1_reviews_hash: Sha256Hex
    prompt_version: NonEmptyString
    prompt_hash: Sha256Hex

    @field_validator(
        "base_question_id", "before_question", "after_question", "reason", "prompt_version"
    )
    @classmethod
    def reject_blank_revision_strings(cls, value: str, info: Any) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator(
        "affected_case_ids", "reviewer_revise_case_ids", "quality_audit_case_ids"
    )
    @classmethod
    def validate_revision_case_ids(
        cls, values: tuple[str, ...], info: Any
    ) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} must not contain blank strings")
        if len(values) != len(set(values)):
            raise ValueError(f"{info.field_name} must not contain duplicate values")
        return values

    @field_validator("changed_at")
    @classmethod
    def require_revision_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("changed_at must include timezone information")
        return value

    @model_validator(mode="after")
    def validate_revision_scope(self):
        if self.before_question == self.after_question:
            raise ValueError("before_question and after_question must differ")
        reviewer = set(self.reviewer_revise_case_ids)
        quality = set(self.quality_audit_case_ids)
        if reviewer & quality:
            raise ValueError("reviewer and quality audit case ids must be disjoint")
        if set(self.affected_case_ids) != reviewer | quality:
            raise ValueError("affected_case_ids must equal reviewer and quality audit union")
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


def _validate_review_input_field_contracts() -> None:
    contracts = (
        (
            "BenchmarkCase",
            frozenset(BenchmarkCase.model_fields),
            REVIEW_CASE_INCLUDED_FIELDS | REVIEW_CASE_EXCLUDED_FIELDS,
        ),
        (
            "ReviewCaseInput",
            frozenset(ReviewCaseInput.model_fields),
            REVIEW_CASE_INCLUDED_FIELDS,
        ),
        (
            "KnowledgeEnvironment",
            frozenset(KnowledgeEnvironment.model_fields),
            KNOWLEDGE_ENVIRONMENT_FIELDS,
        ),
        (
            "ReviewEnvironmentInput",
            frozenset(ReviewEnvironmentInput.model_fields),
            REVIEW_ENVIRONMENT_FIELDS,
        ),
        (
            "CorpusChunk",
            frozenset(CorpusChunk.model_fields),
            REVIEW_CHUNK_INCLUDED_FIELDS | REVIEW_CHUNK_EXCLUDED_FIELDS,
        ),
        (
            "ReviewChunkInput",
            frozenset(ReviewChunkInput.model_fields),
            REVIEW_CHUNK_INCLUDED_FIELDS,
        ),
        ("Claim", frozenset(Claim.model_fields), REVIEW_CLAIM_FIELDS),
        ("ReviewClaimInput", frozenset(ReviewClaimInput.model_fields), REVIEW_CLAIM_FIELDS),
        ("ReviewTargetInput", frozenset(ReviewTargetInput.model_fields), REVIEW_TARGET_FIELDS),
        (
            "ReviewInput",
            frozenset(ReviewInput.model_fields),
            REVIEW_TARGET_FIELDS | {"review_target_hash"},
        ),
    )
    for name, actual, expected in contracts:
        if actual != expected:
            raise RuntimeError(
                f"{name} 字段契约漂移：新增或删除字段后必须显式决定 Reviewer 可见性；"
                f"actual={sorted(actual)!r}, expected={sorted(expected)!r}"
            )


def build_review_target_payload(
    case: BenchmarkCase,
    environment: KnowledgeEnvironment,
    chunks: Iterable[CorpusChunk],
    claims: Iterable[Claim],
) -> ReviewTargetInput:
    """重建 Reviewer 实际可见的无哈希白名单输入。"""
    _validate_review_input_field_contracts()
    case = BenchmarkCase.model_validate(case.model_dump(mode="python"))
    environment = KnowledgeEnvironment.model_validate(environment.model_dump(mode="python"))
    if case.environment_id != environment.environment_id:
        raise ValueError("case environment_id does not match supplied environment")

    chunks_by_id: dict[str, CorpusChunk] = {}
    for raw_chunk in chunks:
        chunk = CorpusChunk.model_validate(raw_chunk.model_dump(mode="python"))
        if chunk.chunk_id in chunks_by_id:
            raise ValueError(f"duplicate corpus chunk id: {chunk.chunk_id}")
        chunks_by_id[chunk.chunk_id] = chunk

    claims_by_id: dict[str, Claim] = {}
    for raw_claim in claims:
        claim = Claim.model_validate(raw_claim.model_dump(mode="python"))
        if claim.claim_id in claims_by_id:
            raise ValueError(f"duplicate corpus claim id: {claim.claim_id}")
        claims_by_id[claim.claim_id] = claim

    def review_chunk(chunk_id: str) -> ReviewChunkInput:
        try:
            chunk = chunks_by_id[chunk_id]
        except KeyError as error:
            raise ValueError(f"environment chunk not found: {chunk_id}") from error
        return ReviewChunkInput(
            chunk_id=chunk.chunk_id,
            source_id=chunk.source_id,
            heading_path=chunk.heading_path,
            text=chunk.text,
            claim_ids=chunk.claim_ids,
        )

    visible_chunks = tuple(review_chunk(item) for item in environment.visible_chunk_ids)
    research_chunks = tuple(review_chunk(item) for item in environment.research_chunk_ids)
    excluded_chunks = tuple(review_chunk(item) for item in environment.excluded_chunk_ids)
    selected_claim_ids = set(case.required_claim_ids)
    for chunk in visible_chunks + research_chunks + excluded_chunks:
        selected_claim_ids.update(chunk.claim_ids)
    pending_claim_ids = list(selected_claim_ids)
    while pending_claim_ids:
        claim_id = pending_claim_ids.pop()
        if claim_id not in claims_by_id:
            raise ValueError(f"review claim not found: {claim_id}")
        for conflict_id in claims_by_id[claim_id].conflicts_with:
            if conflict_id not in selected_claim_ids:
                selected_claim_ids.add(conflict_id)
                pending_claim_ids.append(conflict_id)

    review_claims = tuple(
        ReviewClaimInput(
            claim_id=claim.claim_id,
            statement=claim.statement,
            evidence_chunk_ids=claim.evidence_chunk_ids,
            valid_from=claim.valid_from,
            valid_until=claim.valid_until,
            conflicts_with=claim.conflicts_with,
        )
        for claim in (claims_by_id[claim_id] for claim_id in sorted(selected_claim_ids))
    )
    review_case = ReviewCaseInput(
        schema_version=case.schema_version,
        case_id=case.case_id,
        base_question_id=case.base_question_id,
        question=case.question,
        category=case.category,
        required_claims=case.required_claims,
        allowed_source_ids=case.allowed_source_ids,
        answer_key=case.answer_key,
        local_knowledge_ids=case.local_knowledge_ids,
        need_research=case.need_research,
        environment_id=case.environment_id,
        required_claim_ids=case.required_claim_ids,
        missing_claim_ids=case.missing_claim_ids,
        evidence_chunk_ids=case.evidence_chunk_ids,
        draft_status=case.draft_status,
    )
    return ReviewTargetInput(
        case=review_case,
        environment=ReviewEnvironmentInput(
            environment_id=environment.environment_id,
            environment_hash=environment.environment_hash,
            visible_chunks=visible_chunks,
            research_chunks=research_chunks,
            excluded_chunks=excluded_chunks,
        ),
        claims=review_claims,
    )


def compute_review_target_hash(
    case: BenchmarkCase,
    environment: KnowledgeEnvironment,
    chunks: Iterable[CorpusChunk],
    claims: Iterable[Claim],
) -> str:
    payload = build_review_target_payload(case, environment, chunks, claims)
    return _review_target_hash(payload)


def build_review_input(
    case: BenchmarkCase,
    environment: KnowledgeEnvironment,
    chunks: Iterable[CorpusChunk],
    claims: Iterable[Claim],
) -> ReviewInput:
    payload = build_review_target_payload(case, environment, chunks, claims)
    return ReviewInput(
        **payload.model_dump(mode="python"),
        review_target_hash=_review_target_hash(payload),
    )


def _validate_review_target(
    case: BenchmarkCase,
    environment: KnowledgeEnvironment,
    chunks: Iterable[CorpusChunk],
    claims: Iterable[Claim],
    review: ReviewRecord,
) -> ReviewTargetInput:
    payload = build_review_target_payload(case, environment, chunks, claims)
    expected = _review_target_hash(payload)
    if review.review_target_hash != expected:
        raise ValueError(
            f"case_id={case.case_id}: review_target_hash does not match current draft"
        )
    return payload


def requires_human_review(case: BenchmarkCase, review: ReviewRecord) -> bool:
    case, review = _revalidate_inputs(case, review)
    _validate_case_link(case, review)
    return (
        case.category in {CaseCategory.OUTDATED, CaseCategory.CONFLICT}
        or review.decision in {ReviewDecision.REVISE, ReviewDecision.REJECT}
        or review.reviewer_confidence < 0.8
        or review.prior_rule_failure_count > 0
    )


def apply_review_gate(
    case: BenchmarkCase,
    environment: KnowledgeEnvironment,
    chunks: Iterable[CorpusChunk],
    claims: Iterable[Claim],
    review: ReviewRecord,
) -> BenchmarkCase:
    case, review = _revalidate_inputs(case, review)
    environment = KnowledgeEnvironment.model_validate(environment.model_dump(mode="python"))
    _validate_case_link(case, review)
    target = _validate_review_target(case, environment, chunks, claims, review)
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
    environment_chunk_ids = {
        chunk.chunk_id
        for chunk in (
            target.environment.visible_chunks
            + target.environment.research_chunks
            + target.environment.excluded_chunks
        )
    }
    unknown_refs = set(review.evidence_refs).difference(environment_chunk_ids)
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
