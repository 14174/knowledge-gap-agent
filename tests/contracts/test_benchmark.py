import pytest
from pydantic import ValidationError

from knowledge_gap_agent.contracts.benchmark import BenchmarkCase, CaseCategory


def case(**overrides):
    data = dict(case_id="c1", question="q", annotation_reason="reason",
                required_claims=["claim"], allowed_source_ids=["s1"], answer_key=["a"],
                category=CaseCategory.LOCAL_SUFFICIENT, need_research=False)
    data.update(overrides)
    return BenchmarkCase(**data)


def test_valid_sufficient_case():
    assert case().category is CaseCategory.LOCAL_SUFFICIENT
    assert case(local_knowledge_ids=["k1"]).need_research is False


@pytest.mark.parametrize("category", [CaseCategory.LOCAL_PARTIAL, CaseCategory.LOCAL_MISSING,
                                       CaseCategory.OUTDATED, CaseCategory.CONFLICT])
def test_insufficient_categories_require_research(category):
    with pytest.raises(ValidationError):
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
