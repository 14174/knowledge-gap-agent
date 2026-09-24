from datetime import datetime, timezone
from decimal import Decimal
import math

import pytest
from pydantic import ValidationError

from knowledge_gap_agent.benchmark.review import (
    ReviewDecision,
    ReviewRecord,
    apply_review_gate,
    requires_human_review,
)
from knowledge_gap_agent.contracts.benchmark import (
    BenchmarkCase,
    CaseCategory,
    HumanReviewStatus,
    ReviewStatus,
)


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


def make_review(**overrides: object) -> ReviewRecord:
    values = {
        "case_id": "case1", "decision": ReviewDecision.APPROVE, "issues": [],
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
    assert review.schema_version == "1.0"
    assert review.issues == ("问题",)
    assert review.suggested_changes == ("修改",)
    assert review.evidence_refs == ("evidence",)
    payload = review.model_dump(mode="json")
    assert payload["issues"] == ["问题"]
    assert payload["evidence_refs"] == ["evidence"]
    with pytest.raises(ValidationError, match="1.0"):
        make_review(schema_version="2.0")


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("case_id", " ", "case_id"),
        ("prompt_version", "", "prompt_version"),
        ("model_provider", " ", "model_provider"),
        ("model_name", "", "model_name"),
        ("model_revision", " ", "model_revision"),
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
    assert apply_review_gate(make_case(), review).human_review_status is HumanReviewStatus.PENDING


def test_case_id_mismatch_is_rejected() -> None:
    review = make_review(case_id="other")
    with pytest.raises(ValueError, match="case_id"):
        requires_human_review(make_case(), review)
    with pytest.raises(ValueError, match="case_id"):
        apply_review_gate(make_case(), review)


def test_review_evidence_must_be_subset_of_case_evidence() -> None:
    with pytest.raises(ValueError, match="case1.*evidence_refs.*unknown"):
        apply_review_gate(make_case(), make_review(evidence_refs=["unknown"]))


def test_apply_review_gate_requires_validated_draft_with_diagnostic_status() -> None:
    with pytest.raises(ValueError, match="case1.*generated.*validated"):
        apply_review_gate(make_case(draft_status="generated"), make_review())


@pytest.mark.parametrize("status", ["approved", "revise", "rejected"])
def test_apply_review_gate_refuses_to_rewrite_completed_review(
    status: str,
) -> None:
    with pytest.raises(ValueError, match=rf"case1.*{status}.*pending"):
        apply_review_gate(make_case(review_status=status), make_review())


def test_gate_entry_points_revalidate_bypassed_models() -> None:
    invalid_case = make_case().model_copy(update={"case_id": " "})
    invalid_review = make_review().model_copy(update={"reviewer_confidence": math.nan})
    with pytest.raises(ValidationError, match="case_id"):
        requires_human_review(invalid_case, make_review())
    with pytest.raises(ValidationError, match="reviewer_confidence"):
        requires_human_review(make_case(), invalid_review)
    with pytest.raises(ValidationError, match="case_id"):
        apply_review_gate(invalid_case, make_review())
    with pytest.raises(ValidationError, match="reviewer_confidence"):
        apply_review_gate(make_case(), invalid_review)


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
    updated = apply_review_gate(original, make_review(decision=decision, **details))
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
    updated = apply_review_gate(case, make_review(reviewer_confidence=0.99))
    assert updated.review_status is ReviewStatus.APPROVED
    assert updated.human_review_status is HumanReviewStatus.PENDING


@pytest.mark.parametrize("status", [HumanReviewStatus.APPROVED, HumanReviewStatus.REJECTED])
def test_apply_review_gate_preserves_final_human_decision(status: HumanReviewStatus) -> None:
    with pytest.raises(ValueError, match="human_review_status"):
        apply_review_gate(make_case(human_review_status=status), make_review())
