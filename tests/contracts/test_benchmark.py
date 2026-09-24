import pytest
from pydantic import ValidationError

from knowledge_gap_agent.contracts.benchmark import (
    BenchmarkCase,
    CaseCategory,
    DraftStatus,
    HumanReviewStatus,
    ReviewStatus,
)


def case(**overrides):
    data = dict(case_id="c1", base_question_id="q1", question="q", annotation_reason="reason",
                required_claims=["claim"], allowed_source_ids=["s1"], answer_key=["a"],
                local_knowledge_ids=[], category=CaseCategory.LOCAL_SUFFICIENT,
                need_research=False, environment_id="env1",
                required_claim_ids=["claim1"], missing_claim_ids=[],
                evidence_chunk_ids=["chunk1"], draft_status=DraftStatus.GENERATED,
                review_status=ReviewStatus.PENDING,
                human_review_status=HumanReviewStatus.NOT_REQUIRED)
    data.update(overrides)
    return BenchmarkCase(**data)


def test_valid_sufficient_case():
    assert case().category is CaseCategory.LOCAL_SUFFICIENT
    assert case().local_knowledge_ids == ()
    assert case(local_knowledge_ids=["k1"]).need_research is False


def test_collection_fields_are_frozen_tuples_and_json_arrays():
    item = case(required_claim_ids=["claim1", "claim2"])
    assert item.required_claim_ids == ("claim1", "claim2")
    assert isinstance(item.answer_key, tuple)
    assert item.model_dump(mode="json")["required_claim_ids"] == ["claim1", "claim2"]


def test_schema_version_is_fixed_at_2_0():
    assert case().schema_version == "2.0"
    with pytest.raises(ValidationError, match="2.0"):
        case(schema_version="1.0")


def test_missing_claim_ids_must_be_required():
    with pytest.raises(ValidationError, match="subset"):
        case(missing_claim_ids=["unknown"])


@pytest.mark.parametrize(
    "field",
    ["required_claim_ids", "missing_claim_ids", "evidence_chunk_ids"],
)
def test_identifier_collections_reject_duplicates_and_blank_items(field):
    with pytest.raises(ValidationError, match="duplicate"):
        case(**{field: ["x", "x"]})
    with pytest.raises(ValidationError, match="blank"):
        case(**{field: [" "]})


@pytest.mark.parametrize("category", [CaseCategory.LOCAL_PARTIAL, CaseCategory.LOCAL_MISSING,
                                       CaseCategory.OUTDATED, CaseCategory.CONFLICT])
def test_insufficient_categories_require_research(category):
    with pytest.raises(ValidationError, match=category.value):
        case(category=category, need_research=False)
    assert case(category=category, need_research=True).need_research


def test_sufficient_category_forbids_research():
    with pytest.raises(ValidationError):
        case(need_research=True)


def test_required_fields_and_lists_reject_empty_values():
    for field in ("case_id", "question", "annotation_reason"):
        with pytest.raises(ValidationError):
            case(**{field: ""})
    for field in ("required_claims", "allowed_source_ids", "answer_key"):
        with pytest.raises(ValidationError):
            case(**{field: []})
        with pytest.raises(ValidationError):
            case(**{field: [""]})
    with pytest.raises(ValidationError):
        case(local_knowledge_ids=[""])


def test_extra_fields_and_frozen():
    with pytest.raises(ValidationError):
        case(extra=1)
    item = case()
    with pytest.raises(ValidationError):
        item.question = "changed"


def test_repeated_knowledge_has_no_research_restriction():
    assert case(category=CaseCategory.REPEATED_KNOWLEDGE, need_research=True)
