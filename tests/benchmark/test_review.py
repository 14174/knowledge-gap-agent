from datetime import datetime, timezone
from decimal import Decimal
import json
import math

import pytest
from pydantic import ValidationError

from knowledge_gap_agent.benchmark.review import (
    ReviewDecision,
    ReviewInput,
    ReviewRecord,
    apply_review_gate,
    build_review_input,
    build_review_target_payload,
    compute_review_target_hash,
    requires_human_review,
)
from knowledge_gap_agent.benchmark.models import KnowledgeEnvironment, compute_environment_hash
from knowledge_gap_agent.contracts.benchmark import (
    BenchmarkCase,
    CaseCategory,
    DraftStatus,
    HumanReviewStatus,
    ReviewStatus,
)
from knowledge_gap_agent.corpus.models import Claim, CorpusChunk
from knowledge_gap_agent.corpus.normalize import content_hash
from knowledge_gap_agent.utils.canonical import canonical_json, sha256_hex


def make_case(**overrides: object) -> BenchmarkCase:
    values = {
        "case_id": "case1", "base_question_id": "q1", "question": "问题",
        "category": CaseCategory.LOCAL_SUFFICIENT, "annotation_reason": "理由",
        "required_claims": ["目标"], "allowed_source_ids": ["source1"],
        "answer_key": ["答案"], "local_knowledge_ids": [], "need_research": False,
        "environment_id": "env1", "required_claim_ids": ["claim1"],
        "missing_claim_ids": [], "evidence_chunk_ids": ["evidence", "support"],
        "draft_status": "validated", "review_status": "pending",
        "human_review_status": "not_required",
    }
    values.update(overrides)
    return BenchmarkCase(**values)


def make_environment(**overrides: object) -> KnowledgeEnvironment:
    values = {
        "environment_id": "env1",
        "visible_chunk_ids": ["support"],
        "research_chunk_ids": ["evidence"],
        "excluded_chunk_ids": ["excluded"],
    }
    values.update(overrides)
    values["environment_hash"] = compute_environment_hash(
        values["environment_id"], values["visible_chunk_ids"],
        values["research_chunk_ids"], values["excluded_chunk_ids"],
    )
    return KnowledgeEnvironment(**values)


def make_chunk(chunk_id: str, text: str, claim_ids: tuple[str, ...] = ()) -> CorpusChunk:
    return CorpusChunk(
        chunk_id=chunk_id,
        source_id="source1",
        heading_path=("标题",),
        start_line=1,
        end_line=1,
        text=text,
        token_terms=(),
        content_hash=content_hash(text),
        claim_ids=claim_ids,
    )


def make_chunks() -> tuple[CorpusChunk, ...]:
    return (
        make_chunk("support", "可见正文", ("claim1",)),
        make_chunk("evidence", "研究正文", ("claim1",)),
        make_chunk("excluded", "排除正文"),
    )


def make_claims() -> tuple[Claim, ...]:
    return (
        Claim(
            claim_id="claim1",
            statement="目标",
            evidence_chunk_ids=("support", "evidence"),
            valid_from=None,
            valid_until=None,
            conflicts_with=(),
        ),
    )


def make_review(
    *,
    target_case: BenchmarkCase | None = None,
    target_environment: KnowledgeEnvironment | None = None,
    target_chunks: tuple[CorpusChunk, ...] | None = None,
    target_claims: tuple[Claim, ...] | None = None,
    **overrides: object,
) -> ReviewRecord:
    target_case = target_case or make_case()
    target_environment = target_environment or make_environment()
    target_chunks = target_chunks or make_chunks()
    target_claims = target_claims or make_claims()
    values = {
        "case_id": "case1",
        "review_target_hash": compute_review_target_hash(
            target_case, target_environment, target_chunks, target_claims
        ),
        "decision": ReviewDecision.APPROVE, "issues": [],
        "suggested_changes": [], "evidence_refs": ["evidence"],
        "reviewer_confidence": 0.8, "labeler_reasoning_seen": False,
        "prior_rule_failure_count": 0,
        "prompt_version": "review-v1", "prompt_hash": "a" * 64,
        "model_provider": "provider", "model_name": "model",
        "model_revision": "revision",
        "reviewed_at": datetime(2026, 9, 24, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return ReviewRecord(**values)


def test_review_record_has_fixed_schema_and_json_arrays() -> None:
    review = make_review(issues=["问题"], suggested_changes=["修改"])
    assert review.schema_version == "2.0"
    assert review.issues == ("问题",)
    assert review.suggested_changes == ("修改",)
    assert review.evidence_refs == ("evidence",)
    payload = review.model_dump(mode="json")
    assert payload["issues"] == ["问题"]
    assert payload["evidence_refs"] == ["evidence"]
    with pytest.raises(ValidationError, match="2.0"):
        make_review(schema_version="1.0")


def test_review_target_hash_binds_complete_case_and_environment() -> None:
    case = make_case()
    environment = make_environment()
    chunks = make_chunks()
    claims = make_claims()
    baseline = compute_review_target_hash(case, environment, chunks, claims)

    assert len(baseline) == 64
    assert compute_review_target_hash(case, environment, chunks, claims) == baseline
    mutations = (
        case.model_copy(update={"question": "新问题"}),
        case.model_copy(update={"answer_key": ("新答案",)}),
        case.model_copy(update={"category": CaseCategory.REPEATED_KNOWLEDGE}),
        case.model_copy(update={"draft_status": DraftStatus.GENERATED}),
    )
    assert all(
        compute_review_target_hash(item, environment, chunks, claims) != baseline
        for item in mutations
    )
    review_output_changed = case.model_copy(update={
        "review_status": ReviewStatus.APPROVED,
        "human_review_status": HumanReviewStatus.PENDING,
    })
    assert compute_review_target_hash(
        review_output_changed, environment, chunks, claims
    ) == baseline
    target_payload = build_review_target_payload(case, environment, chunks, claims)
    assert "draft_status" in type(target_payload.case).model_fields
    assert "review_status" not in type(target_payload.case).model_fields
    assert "human_review_status" not in type(target_payload.case).model_fields
    assert "annotation_reason" not in type(target_payload.case).model_fields
    with pytest.raises(ValueError, match="review_status"):
        apply_review_gate(
            review_output_changed,
            environment,
            chunks,
            claims,
            make_review(target_case=case, target_environment=environment),
        )
    changed_environment = make_environment(visible_chunk_ids=["other"])
    changed_chunks = chunks + (make_chunk("other", "其他正文"),)
    assert compute_review_target_hash(
        case, changed_environment, changed_chunks, claims
    ) != baseline


def test_review_target_hash_revalidates_and_requires_matching_environment() -> None:
    with pytest.raises(ValueError, match="environment_id"):
        compute_review_target_hash(
            make_case(), make_environment(environment_id="other"), make_chunks(), make_claims()
        )
    invalid = make_case().model_copy(update={"question": ""})
    with pytest.raises(ValidationError, match="question"):
        compute_review_target_hash(invalid, make_environment(), make_chunks(), make_claims())


def test_apply_review_gate_rejects_review_for_changed_target() -> None:
    case = make_case()
    environment = make_environment()
    chunks = make_chunks()
    claims = make_claims()
    review = make_review(
        review_target_hash=compute_review_target_hash(case, environment, chunks, claims)
    )
    changed = case.model_copy(update={"answer_key": ("新答案",)})

    with pytest.raises(ValueError, match="review_target_hash"):
        apply_review_gate(changed, environment, chunks, claims, review)


def test_review_input_is_explicit_auditable_whitelist_without_labeler_reasoning() -> None:
    case = make_case()
    environment = make_environment()
    chunks = (
        make_chunk("support", "可见正文", ("claim1",)),
        make_chunk("evidence", "研究正文", ("claim1",)),
        make_chunk("excluded", "排除正文"),
    )
    claims = (
        Claim(
            claim_id="claim1",
            statement="目标",
            evidence_chunk_ids=("support", "evidence"),
            valid_from=None,
            valid_until=None,
            conflicts_with=(),
        ),
    )

    review_input = build_review_input(case, environment, chunks, claims)
    target = build_review_target_payload(case, environment, chunks, claims)

    assert isinstance(review_input, ReviewInput)
    assert review_input.review_target_hash == sha256_hex(target.model_dump(mode="json"))
    assert review_input.review_target_hash == compute_review_target_hash(
        case, environment, chunks, claims
    )
    assert [chunk.text for chunk in review_input.environment.visible_chunks] == ["可见正文"]
    assert [chunk.text for chunk in review_input.environment.research_chunks] == ["研究正文"]
    assert [chunk.text for chunk in review_input.environment.excluded_chunks] == ["排除正文"]
    assert [claim.claim_id for claim in review_input.claims] == ["claim1"]
    rendered = canonical_json(review_input.model_dump(mode="json"))
    assert "annotation_reason" not in rendered
    assert "理由" not in rendered
    assert "review_status" not in type(review_input.case).model_fields
    assert "human_review_status" not in type(review_input.case).model_fields


@pytest.mark.parametrize("entry_point", ["model_validate", "constructor", "json"])
@pytest.mark.parametrize(
    "mutation",
    ["case_question", "chunk_text", "claim_statement", "review_target_hash"],
)
def test_review_input_rejects_tampered_payload_at_every_parse_entry(
    entry_point: str,
    mutation: str,
) -> None:
    review_input = build_review_input(
        make_case(), make_environment(), make_chunks(), make_claims()
    )
    payload = json.loads(canonical_json(review_input.model_dump(mode="json")))
    if mutation == "case_question":
        payload["case"]["question"] = "篡改问题"
    elif mutation == "chunk_text":
        payload["environment"]["visible_chunks"][0]["text"] = "篡改正文"
    elif mutation == "claim_statement":
        payload["claims"][0]["statement"] = "篡改主张"
    else:
        payload["review_target_hash"] = "0" * 64

    with pytest.raises(ValidationError, match="review_target_hash"):
        if entry_point == "model_validate":
            ReviewInput.model_validate(payload)
        elif entry_point == "constructor":
            ReviewInput(**payload)
        else:
            ReviewInput.model_validate_json(canonical_json(payload))


def test_review_input_model_copy_bypass_is_caught_when_public_entry_revalidates() -> None:
    review_input = build_review_input(
        make_case(), make_environment(), make_chunks(), make_claims()
    )
    bypassed = review_input.model_copy(update={"review_target_hash": "0" * 64})

    assert bypassed.review_target_hash == "0" * 64
    with pytest.raises(ValidationError, match="review_target_hash"):
        ReviewInput.model_validate(bypassed.model_dump(mode="python"))


def test_review_target_hash_binds_reviewer_visible_chunk_and_claim_content() -> None:
    case = make_case()
    environment = make_environment()
    chunks = (
        make_chunk("support", "可见正文", ("claim1",)),
        make_chunk("evidence", "研究正文", ("claim1",)),
        make_chunk("excluded", "排除正文"),
    )
    claim = Claim(
        claim_id="claim1",
        statement="目标",
        evidence_chunk_ids=("support", "evidence"),
        valid_from=None,
        valid_until=None,
        conflicts_with=(),
    )
    baseline = build_review_input(case, environment, chunks, (claim,)).review_target_hash

    changed_chunks = (
        make_chunk("support", "已变更的可见正文", ("claim1",)),
        chunks[0].model_copy(update={"source_id": "source2"}),
        chunks[0].model_copy(update={"heading_path": ("新标题",)}),
        chunks[0].model_copy(update={"claim_ids": ()}),
    )
    changed_claims = (
        claim.model_copy(update={"statement": "已变更目标"}),
        claim.model_copy(update={"valid_until": datetime(2026, 9, 24, tzinfo=timezone.utc)}),
        claim.model_copy(update={"evidence_chunk_ids": ("support",)}),
    )

    assert all(
        build_review_input(
            case, environment, (changed_chunk, chunks[1], chunks[2]), (claim,)
        ).review_target_hash != baseline
        for changed_chunk in changed_chunks
    )
    assert all(
        build_review_input(case, environment, chunks, (changed,)).review_target_hash
        != baseline
        for changed in changed_claims
    )

    conflicting = claim.model_copy(update={"conflicts_with": ("claim2",)})
    claim2 = Claim(
        claim_id="claim2",
        statement="互斥目标",
        evidence_chunk_ids=("excluded",),
        valid_from=None,
        valid_until=None,
        conflicts_with=("claim1",),
    )
    assert build_review_input(
        case, environment, chunks, (conflicting, claim2)
    ).review_target_hash != baseline


def test_apply_review_gate_rejects_old_review_after_visible_content_changes() -> None:
    case = make_case()
    environment = make_environment()
    chunks = make_chunks()
    claims = make_claims()
    review = make_review(
        target_case=case,
        target_environment=environment,
        target_chunks=chunks,
        target_claims=claims,
    )
    claim = claims[0]
    claim2 = Claim(
        claim_id="claim2",
        statement="互斥目标",
        evidence_chunk_ids=("excluded",),
        valid_from=None,
        valid_until=None,
        conflicts_with=("claim1",),
    )
    changed_inputs = (
        ((make_chunk("support", "已变更正文", ("claim1",)), chunks[1], chunks[2]), claims),
        (chunks, (claim.model_copy(update={"statement": "已变更目标"}),)),
        (chunks, (claim.model_copy(update={
            "valid_until": datetime(2026, 9, 24, tzinfo=timezone.utc),
        }),)),
        (chunks, (claim.model_copy(update={"evidence_chunk_ids": ("support",)}),)),
        (chunks, (claim.model_copy(update={"conflicts_with": ("claim2",)}), claim2)),
    )

    for changed_chunks, changed_claims in changed_inputs:
        with pytest.raises(ValueError, match="review_target_hash"):
            apply_review_gate(
                case,
                environment,
                changed_chunks,
                changed_claims,
                review,
            )


def test_review_target_rejects_chunk_text_tampering_with_stale_content_hash() -> None:
    chunks = make_chunks()
    tampered = chunks[0].model_copy(update={"text": "篡改正文"})

    with pytest.raises(ValidationError, match="content_hash"):
        compute_review_target_hash(
            make_case(),
            make_environment(),
            (tampered, chunks[1], chunks[2]),
            make_claims(),
        )


def test_review_target_hash_excludes_annotation_reason_not_seen_by_reviewer() -> None:
    case = make_case()
    environment = make_environment()
    chunks = (
        make_chunk("support", "可见正文", ("claim1",)),
        make_chunk("evidence", "研究正文", ("claim1",)),
        make_chunk("excluded", "排除正文"),
    )
    claims = (
        Claim(
            claim_id="claim1",
            statement="目标",
            evidence_chunk_ids=("support", "evidence"),
            valid_from=None,
            valid_until=None,
            conflicts_with=(),
        ),
    )

    baseline = build_review_input(case, environment, chunks, claims).review_target_hash
    changed = build_review_input(
        case.model_copy(update={"annotation_reason": "未向 Reviewer 展示的新理由"}),
        environment,
        chunks,
        claims,
    ).review_target_hash

    assert changed == baseline


def test_review_evidence_may_reference_any_chunk_in_environment() -> None:
    case = make_case()
    environment = make_environment()
    chunks = (
        make_chunk("support", "可见正文", ("claim1",)),
        make_chunk("evidence", "研究正文", ("claim1",)),
        make_chunk("excluded", "受控排除正文"),
    )
    claims = (
        Claim(
            claim_id="claim1",
            statement="目标",
            evidence_chunk_ids=("support", "evidence"),
            valid_from=None,
            valid_until=None,
            conflicts_with=(),
        ),
    )
    target = build_review_input(case, environment, chunks, claims)
    review = make_review(
        review_target_hash=target.review_target_hash,
        evidence_refs=("excluded",),
    )

    updated = apply_review_gate(case, environment, chunks, claims, review)

    assert updated.review_status is ReviewStatus.APPROVED


def test_review_input_field_contract_rejects_future_benchmark_case_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        BenchmarkCase.model_fields,
        "future_field",
        BenchmarkCase.model_fields["question"],
    )
    with pytest.raises(RuntimeError, match="BenchmarkCase.*字段|field"):
        build_review_input(
            make_case(),
            make_environment(),
            (
                make_chunk("support", "可见正文", ("claim1",)),
                make_chunk("evidence", "研究正文", ("claim1",)),
                make_chunk("excluded", "排除正文"),
            ),
            (
                Claim(
                    claim_id="claim1",
                    statement="目标",
                    evidence_chunk_ids=("support", "evidence"),
                    valid_from=None,
                    valid_until=None,
                    conflicts_with=(),
                ),
            ),
        )


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("case_id", " ", "case_id"),
        ("prompt_version", "", "prompt_version"),
        ("model_provider", " ", "model_provider"),
        ("model_name", "", "model_name"),
        ("model_revision", " ", "model_revision"),
        ("review_target_hash", "A" * 64, "review_target_hash"),
        ("review_target_hash", "a" * 63, "review_target_hash"),
        ("prompt_hash", "A" * 64, "prompt_hash"),
        ("prompt_hash", "a" * 63, "prompt_hash"),
    ],
)
def test_review_record_rejects_invalid_scalar_fields(field: str, value: object, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        make_review(**{field: value})


@pytest.mark.parametrize("field", ["issues", "suggested_changes", "evidence_refs"])
def test_review_record_rejects_blank_and_duplicate_tuple_items(field: str) -> None:
    with pytest.raises(ValidationError, match="blank"):
        make_review(**{field: [" "]})
    with pytest.raises(ValidationError, match="duplicate"):
        make_review(**{field: ["same", "same"]})


@pytest.mark.parametrize(
    "value",
    [-0.01, 1.01, math.inf, -math.inf, math.nan, True, False, 0, 1, Decimal("0.8"), "0.8"],
)
def test_review_record_rejects_invalid_confidence(value: object) -> None:
    with pytest.raises(ValidationError, match="reviewer_confidence"):
        make_review(reviewer_confidence=value)


@pytest.mark.parametrize("value", [-1, True, False, 1.0, "1"])
def test_prior_rule_failure_count_requires_nonnegative_strict_integer(value: object) -> None:
    with pytest.raises(ValidationError, match="prior_rule_failure_count"):
        make_review(prior_rule_failure_count=value)


def test_prior_rule_failure_count_is_required() -> None:
    payload = make_review().model_dump()
    del payload["prior_rule_failure_count"]
    with pytest.raises(ValidationError, match="prior_rule_failure_count"):
        ReviewRecord(**payload)


def test_review_record_requires_timezone_aware_datetime() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        make_review(reviewed_at=datetime(2026, 9, 24))


def test_review_record_proves_reviewer_did_not_see_labeler_reasoning() -> None:
    assert make_review().labeler_reasoning_seen is False
    with pytest.raises(ValidationError, match="False|false"):
        make_review(labeler_reasoning_seen=True)


def test_review_record_requires_evidence_and_decision_specific_details() -> None:
    with pytest.raises(ValidationError, match="evidence_refs"):
        make_review(evidence_refs=[])
    with pytest.raises(ValidationError, match="issues"):
        make_review(decision="revise", issues=[], suggested_changes=["修改"])
    with pytest.raises(ValidationError, match="suggested_changes"):
        make_review(decision="revise", issues=["问题"], suggested_changes=[])
    with pytest.raises(ValidationError, match="issues"):
        make_review(decision="reject", issues=[])
    assert make_review(decision="reject", issues=["问题"], suggested_changes=[])


@pytest.mark.parametrize("category", [CaseCategory.OUTDATED, CaseCategory.CONFLICT])
def test_high_risk_category_always_requires_human_review(category: CaseCategory) -> None:
    case = make_case(category=category, need_research=True)
    assert requires_human_review(case, make_review(reviewer_confidence=0.99))


@pytest.mark.parametrize("decision", [ReviewDecision.REVISE, ReviewDecision.REJECT])
def test_non_approval_requires_human_review(decision: ReviewDecision) -> None:
    details = {"issues": ["问题"]}
    if decision is ReviewDecision.REVISE:
        details["suggested_changes"] = ["修改"]
    assert requires_human_review(make_case(), make_review(decision=decision, **details))


def test_confidence_threshold_is_strictly_below_point_eight() -> None:
    assert requires_human_review(make_case(), make_review(reviewer_confidence=0.79))
    assert not requires_human_review(make_case(), make_review(reviewer_confidence=0.8))


def test_prior_rule_failure_always_requires_human_review() -> None:
    review = make_review(reviewer_confidence=0.99, prior_rule_failure_count=1)
    assert requires_human_review(make_case(), review)
    assert apply_review_gate(
        make_case(), make_environment(), make_chunks(), make_claims(), review
    ).human_review_status is HumanReviewStatus.PENDING


def test_case_id_mismatch_is_rejected() -> None:
    review = make_review(case_id="other")
    with pytest.raises(ValueError, match="case_id"):
        requires_human_review(make_case(), review)
    with pytest.raises(ValueError, match="case_id"):
        apply_review_gate(
            make_case(), make_environment(), make_chunks(), make_claims(), review
        )


def test_review_evidence_must_be_subset_of_environment_chunks() -> None:
    with pytest.raises(ValueError, match="case1.*evidence_refs.*unknown"):
        apply_review_gate(
            make_case(), make_environment(), make_chunks(), make_claims(),
            make_review(evidence_refs=["unknown"]),
        )


def test_apply_review_gate_requires_validated_draft_with_diagnostic_status() -> None:
    case = make_case(draft_status="generated")
    with pytest.raises(ValueError, match="case1.*generated.*validated"):
        apply_review_gate(
            case, make_environment(), make_chunks(), make_claims(),
            make_review(target_case=case),
        )


@pytest.mark.parametrize("status", ["approved", "revise", "rejected"])
def test_apply_review_gate_refuses_to_rewrite_completed_review(
    status: str,
) -> None:
    case = make_case(review_status=status)
    with pytest.raises(ValueError, match=rf"case1.*{status}.*pending"):
        apply_review_gate(
            case, make_environment(), make_chunks(), make_claims(),
            make_review(target_case=case),
        )


def test_gate_entry_points_revalidate_bypassed_models() -> None:
    invalid_case = make_case().model_copy(update={"case_id": " "})
    invalid_review = make_review().model_copy(update={"reviewer_confidence": math.nan})
    with pytest.raises(ValidationError, match="case_id"):
        requires_human_review(invalid_case, make_review())
    with pytest.raises(ValidationError, match="reviewer_confidence"):
        requires_human_review(make_case(), invalid_review)
    with pytest.raises(ValidationError, match="case_id"):
        apply_review_gate(
            invalid_case, make_environment(), make_chunks(), make_claims(), make_review()
        )
    with pytest.raises(ValidationError, match="reviewer_confidence"):
        apply_review_gate(
            make_case(), make_environment(), make_chunks(), make_claims(), invalid_review
        )


@pytest.mark.parametrize(
    "decision,expected_review,expected_human,details",
    [
        (ReviewDecision.APPROVE, ReviewStatus.APPROVED,
         HumanReviewStatus.NOT_REQUIRED, {}),
        (ReviewDecision.REVISE, ReviewStatus.REVISE,
         HumanReviewStatus.PENDING, {"issues": ["问题"], "suggested_changes": ["修改"]}),
        (ReviewDecision.REJECT, ReviewStatus.REJECTED,
         HumanReviewStatus.PENDING, {"issues": ["问题"]}),
    ],
)
def test_apply_review_gate_maps_decisions_without_automatic_human_approval(
    decision: ReviewDecision,
    expected_review: ReviewStatus,
    expected_human: HumanReviewStatus,
    details: dict[str, object],
    ) -> None:
    original = make_case()
    updated = apply_review_gate(
        original,
        make_environment(),
        make_chunks(),
        make_claims(),
        make_review(target_case=original, decision=decision, **details),
    )
    assert updated.review_status is expected_review
    assert updated.human_review_status is expected_human
    assert updated.human_review_status is not HumanReviewStatus.APPROVED
    assert original.review_status is ReviewStatus.PENDING
    assert original.human_review_status is HumanReviewStatus.NOT_REQUIRED
    original_payload = original.model_dump()
    updated_payload = updated.model_dump()
    for field in type(original).model_fields:
        if field not in {"review_status", "human_review_status"}:
            assert updated_payload[field] == original_payload[field]


def test_approved_high_risk_review_still_sets_human_pending() -> None:
    case = make_case(category=CaseCategory.OUTDATED, need_research=True)
    updated = apply_review_gate(
        case,
        make_environment(),
        make_chunks(),
        make_claims(),
        make_review(target_case=case, reviewer_confidence=0.99),
    )
    assert updated.review_status is ReviewStatus.APPROVED
    assert updated.human_review_status is HumanReviewStatus.PENDING


@pytest.mark.parametrize("status", [HumanReviewStatus.APPROVED, HumanReviewStatus.REJECTED])
def test_apply_review_gate_preserves_final_human_decision(status: HumanReviewStatus) -> None:
    case = make_case(human_review_status=status)
    with pytest.raises(ValueError, match="human_review_status"):
        apply_review_gate(
            case, make_environment(), make_chunks(), make_claims(),
            make_review(target_case=case),
        )
