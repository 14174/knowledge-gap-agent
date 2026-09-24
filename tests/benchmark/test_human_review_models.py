import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from knowledge_gap_agent.benchmark import (
    HumanReviewDecision,
    HumanReviewRecord,
    HumanRevisionRecord,
)


def valid_human_review(**changes: object) -> HumanReviewRecord:
    values = {
        "case_id": "case-1",
        "review_target_hash": "a" * 64,
        "decision": "approved",
        "actor": "reviewer@example.com",
        "reason": "标签和三池证据关系一致。",
        "reviewed_at": datetime(2026, 9, 25, tzinfo=UTC),
        "requested_changes": [],
    }
    values.update(changes)
    return HumanReviewRecord(**values)


def valid_human_revision(**changes: object) -> HumanRevisionRecord:
    values = {
        "case_id": "case-1",
        "actor": "editor@example.com",
        "reason": "按人工意见修正答案键。",
        "before_review_target_hash": "a" * 64,
        "after_review_target_hash": "b" * 64,
        "before_summary": "答案键包含未受证据支持的结论。",
        "after_summary": "移除未受证据支持的答案键条目。",
        "changed_at": datetime(2026, 9, 25, tzinfo=UTC),
    }
    values.update(changes)
    return HumanRevisionRecord(**values)


def test_human_review_decisions_are_distinct_from_model_decisions() -> None:
    assert [decision.value for decision in HumanReviewDecision] == [
        "approved",
        "rejected",
        "revise",
    ]


def test_human_review_is_frozen_forbids_extras_and_serializes_tuple_as_array() -> None:
    review = valid_human_review(requested_changes=["补充证据映射"])

    assert review.requested_changes == ("补充证据映射",)
    assert isinstance(review.requested_changes, tuple)
    assert json.loads(review.model_dump_json())["requested_changes"] == ["补充证据映射"]
    with pytest.raises(ValidationError, match="frozen"):
        review.reason = "改写原因"
    with pytest.raises(ValidationError, match="extra"):
        valid_human_review(extra="forbidden")


@pytest.mark.parametrize("field", ["case_id", "actor", "reason"])
def test_human_review_rejects_blank_required_strings(field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        valid_human_review(**{field: "   "})


@pytest.mark.parametrize(
    "requested_changes",
    [[""], ["   "], ["补充证据", "补充证据"]],
)
def test_human_review_rejects_blank_or_duplicate_requested_changes(
    requested_changes: list[str],
) -> None:
    with pytest.raises(ValidationError, match="requested_changes"):
        valid_human_review(requested_changes=requested_changes)


def test_human_revise_requires_requested_changes() -> None:
    with pytest.raises(ValidationError, match="requested_changes"):
        valid_human_review(decision="revise", requested_changes=[])


def test_human_review_rejects_naive_reviewed_at() -> None:
    with pytest.raises(ValidationError, match="reviewed_at"):
        valid_human_review(reviewed_at=datetime(2026, 9, 25))


@pytest.mark.parametrize(
    "changes",
    [
        {"reviewed_at": datetime(2026, 9, 25)},
        {"decision": HumanReviewDecision.REVISE, "requested_changes": ()},
        {"review_target_hash": "not-a-sha256"},
    ],
)
def test_human_review_dump_then_validate_rejects_model_copy_bypasses(
    changes: dict[str, object],
) -> None:
    bypassed = valid_human_review().model_copy(update=changes)

    # 不直接 model_validate(instance)：它不是项目跨信任边界的重验方式。
    with pytest.raises(ValidationError):
        HumanReviewRecord.model_validate(bypassed.model_dump(mode="python"))


def test_human_revision_is_frozen_and_forbids_extras() -> None:
    revision = valid_human_revision()

    assert revision.record_type == "human_review_revision"
    with pytest.raises(ValidationError, match="frozen"):
        revision.reason = "改写原因"
    with pytest.raises(ValidationError, match="extra"):
        valid_human_revision(extra="forbidden")


@pytest.mark.parametrize(
    "field",
    ["case_id", "actor", "reason", "before_summary", "after_summary"],
)
def test_human_revision_rejects_blank_required_strings(field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        valid_human_revision(**{field: "   "})


@pytest.mark.parametrize("field", ["before_summary", "after_summary"])
@pytest.mark.parametrize("placeholder", [" 已修复。 ", "修复!", " 已 处 理，\t"])
def test_human_revision_rejects_normalized_placeholder_summary(
    field: str, placeholder: str
) -> None:
    with pytest.raises(ValidationError, match=field):
        valid_human_revision(**{field: placeholder})


def test_human_revision_requires_meaningfully_different_summaries() -> None:
    with pytest.raises(ValidationError, match="before_summary.*after_summary.*differ"):
        valid_human_revision(
            before_summary="  相同的改动摘要  ",
            after_summary="相同的改动摘要",
        )


def test_human_revision_normalizes_whitespace_and_punctuation_when_comparing_summaries(
) -> None:
    with pytest.raises(ValidationError, match="before_summary.*after_summary.*differ"):
        valid_human_revision(
            before_summary="相同 的改动 摘要。",
            after_summary="相同的改动摘要!",
        )


def test_human_revision_requires_distinct_target_hashes() -> None:
    with pytest.raises(ValidationError, match="must differ"):
        valid_human_revision(after_review_target_hash="a" * 64)


def test_human_revision_rejects_naive_changed_at() -> None:
    with pytest.raises(ValidationError, match="changed_at"):
        valid_human_revision(changed_at=datetime(2026, 9, 25))


@pytest.mark.parametrize(
    "changes",
    [
        {"changed_at": datetime(2026, 9, 25)},
        {"after_review_target_hash": "a" * 64},
        {"before_review_target_hash": "not-a-sha256"},
    ],
)
def test_human_revision_dump_then_validate_rejects_model_copy_bypasses(
    changes: dict[str, object],
) -> None:
    bypassed = valid_human_revision().model_copy(update=changes)

    # 不直接 model_validate(instance)；转储后重验必须恢复全部字段和模型校验。
    with pytest.raises(ValidationError):
        HumanRevisionRecord.model_validate(bypassed.model_dump(mode="python"))
