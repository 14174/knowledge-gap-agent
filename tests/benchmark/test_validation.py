from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from knowledge_gap_agent.benchmark import (
    LABEL_FIELDS,
    KnowledgeEnvironment,
    build_runtime_payload,
    compute_environment_hash,
    validate_case,
    validate_dataset,
)
from knowledge_gap_agent.contracts.benchmark import BenchmarkCase, CaseCategory
from knowledge_gap_agent.corpus.models import Claim, CorpusChunk
from knowledge_gap_agent.corpus.normalize import content_hash


def make_environment(**overrides: object) -> KnowledgeEnvironment:
    values = {
        "environment_id": "env1",
        "visible_chunk_ids": ["visible"],
        "research_chunk_ids": ["evidence"],
        "excluded_chunk_ids": ["excluded"],
    }
    values.update(overrides)
    values["environment_hash"] = compute_environment_hash(
        values["environment_id"], values["visible_chunk_ids"],
        values["research_chunk_ids"], values["excluded_chunk_ids"],
    )
    return KnowledgeEnvironment(**values)


def make_case(**overrides: object) -> BenchmarkCase:
    values = {
        "case_id": "case1", "base_question_id": "q1", "question": "问题",
        "category": CaseCategory.LOCAL_PARTIAL, "annotation_reason": "理由",
        "required_claims": ["目标"], "allowed_source_ids": ["source1"],
        "answer_key": ["答案"], "local_knowledge_ids": [], "need_research": True,
        "environment_id": "env1", "required_claim_ids": ["claim1"],
        "missing_claim_ids": ["claim1"], "evidence_chunk_ids": ["evidence"],
        "draft_status": "generated", "review_status": "pending",
        "human_review_status": "not_required",
    }
    values.update(overrides)
    return BenchmarkCase(**values)


def make_chunk(chunk_id: str, claim_ids: tuple[str, ...]) -> CorpusChunk:
    text = f"text-{chunk_id}"
    return CorpusChunk(chunk_id=chunk_id, source_id="source1", heading_path=(),
                       start_line=1, end_line=1, text=text, token_terms=(),
                       content_hash=content_hash(text), claim_ids=claim_ids)


def make_claim() -> Claim:
    return Claim(claim_id="claim1", statement="目标", evidence_chunk_ids=("evidence",),
                 valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc), valid_until=None,
                 conflicts_with=())


def valid_data():
    environment = make_environment()
    chunks = {item.chunk_id: item for item in (
        make_chunk("visible", ()), make_chunk("evidence", ("claim1",)),
        make_chunk("excluded", ()),
    )}
    return make_case(category="local_missing"), environment, chunks, {"claim1": make_claim()}


def test_environment_rejects_overlap_duplicate_and_bad_hash():
    with pytest.raises(ValidationError, match="disjoint"):
        make_environment(visible_chunk_ids=["visible"], research_chunk_ids=["visible"])
    with pytest.raises(ValidationError, match="duplicate"):
        make_environment(visible_chunk_ids=["visible", "visible"])
    values = make_environment().model_dump()
    values["environment_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="environment_hash"):
        KnowledgeEnvironment(**values)


def test_environment_canonicalizes_pool_order_and_hash():
    first = make_environment(visible_chunk_ids=["z", "a"])
    second = make_environment(visible_chunk_ids=["a", "z"])
    assert first.visible_chunk_ids == ("a", "z")
    assert first.environment_hash == second.environment_hash
    assert first.model_dump(mode="json")["visible_chunk_ids"] == ["a", "z"]


def test_validate_case_accepts_consistent_references():
    assert validate_case(*valid_data()) == ()


@pytest.mark.parametrize("mutation, expected_code", [
    ({"environment_id": "other"}, "environment_id_mismatch"),
    ({"required_claim_ids": ["unknown"], "missing_claim_ids": []}, "claim_not_found"),
    ({"evidence_chunk_ids": ["unknown"]}, "chunk_not_found"),
    ({"evidence_chunk_ids": ["excluded"]}, "evidence_excluded"),
])
def test_validate_case_reports_reference_errors(mutation, expected_code):
    case, environment, chunks, claims = valid_data()
    issues = validate_case(make_case(**mutation), environment, chunks, claims)
    assert expected_code in {issue.code for issue in issues}
    assert all(issue.case_id == "case1" and isinstance(issue.refs, tuple) for issue in issues)


def test_validate_case_reports_coverage_and_visible_missing_claim_leak():
    case, environment, chunks, claims = valid_data()
    claims["claim1"] = claims["claim1"].model_copy(update={"evidence_chunk_ids": ("visible",)})
    chunks["visible"] = chunks["visible"].model_copy(update={"claim_ids": ("claim1",)})
    issues = validate_case(case, environment, chunks, claims)
    assert {issue.code for issue in issues} >= {"required_claim_without_evidence", "missing_claim_visible"}


def test_validate_case_rejects_case_and_required_claim_evidence_outside_environment():
    case, environment, chunks, claims = valid_data()
    chunks["outside"] = make_chunk("outside", ("claim1",))
    claims["claim1"] = claims["claim1"].model_copy(update={"evidence_chunk_ids": ("outside",)})
    issues = validate_case(make_case(evidence_chunk_ids=["outside"]), environment, chunks, claims)
    assert "evidence_outside_environment" in {issue.code for issue in issues}


def test_validate_case_rejects_evidence_unrelated_to_required_claims():
    case, environment, chunks, claims = valid_data()
    chunks["visible"] = chunks["visible"].model_copy(update={"claim_ids": ("other",)})
    issues = validate_case(
        make_case(evidence_chunk_ids=["evidence", "visible"]),
        environment,
        chunks,
        claims,
    )
    unrelated = [issue for issue in issues if issue.code == "case_evidence_without_required_claim"]
    assert len(unrelated) == 1
    assert unrelated[0].refs == ("visible",)


def test_validate_case_rejects_evidence_from_disallowed_source():
    case, environment, chunks, claims = valid_data()
    chunks["evidence"] = chunks["evidence"].model_copy(update={"source_id": "other-source"})
    issues = validate_case(case, environment, chunks, claims)
    assert "evidence_source_not_allowed" in {issue.code for issue in issues}


def test_local_sufficient_requires_no_missing_and_visible_support():
    case, environment, chunks, claims = valid_data()
    sufficient = make_case(category="local_sufficient", need_research=False,
                           missing_claim_ids=[], evidence_chunk_ids=["evidence"])
    issues = validate_case(sufficient, environment, chunks, claims)
    assert "local_sufficient_claim_not_visible" in {issue.code for issue in issues}
    chunks["visible"] = chunks["visible"].model_copy(update={"claim_ids": ("claim1",)})
    claims["claim1"] = claims["claim1"].model_copy(
        update={"evidence_chunk_ids": ("visible", "evidence")}
    )
    assert not {issue.code for issue in validate_case(sufficient, environment, chunks, claims)} & {
        "local_sufficient_missing_claims", "local_sufficient_claim_not_visible",
    }
    invalid = make_case(category="local_sufficient", need_research=False,
                        missing_claim_ids=["claim1"])
    assert "local_sufficient_missing_claims" in {
        issue.code for issue in validate_case(invalid, environment, chunks, claims)
    }


@pytest.mark.parametrize("category", ["local_partial", "local_missing"])
def test_missing_categories_require_research_for_missing_and_visible_for_known(category):
    environment = make_environment()
    chunks = {
        "visible": make_chunk("visible", ("known",)),
        "evidence": make_chunk("evidence", ("missing",)),
        "excluded": make_chunk("excluded", ()),
    }
    claims = {
        "known": make_claim().model_copy(update={
            "claim_id": "known", "evidence_chunk_ids": ("visible",),
        }),
        "missing": make_claim().model_copy(update={
            "claim_id": "missing", "evidence_chunk_ids": ("evidence",),
        }),
    }
    item = make_case(category=category, required_claim_ids=["known", "missing"],
                     missing_claim_ids=["missing"], evidence_chunk_ids=["visible", "evidence"])
    semantic_codes = {issue.code for issue in validate_case(item, environment, chunks, claims)}
    assert not semantic_codes & {"missing_claim_not_research_supported", "known_claim_not_visible"}
    bad_chunks = dict(chunks)
    bad_chunks["visible"] = bad_chunks["visible"].model_copy(update={"claim_ids": ()})
    bad_chunks["evidence"] = bad_chunks["evidence"].model_copy(update={"claim_ids": ("known",)})
    semantic_codes = {issue.code for issue in validate_case(item, environment, bad_chunks, claims)}
    assert {"missing_claim_not_research_supported", "known_claim_not_visible"} <= semantic_codes


@pytest.mark.parametrize("missing_ids", [[], ["known", "missing"]])
def test_local_partial_requires_nonempty_true_subset(missing_ids):
    environment = make_environment()
    chunks = {
        "visible": make_chunk("visible", ("known",)),
        "evidence": make_chunk("evidence", ("missing",)),
        "excluded": make_chunk("excluded", ()),
    }
    claims = {
        "known": make_claim().model_copy(update={
            "claim_id": "known", "evidence_chunk_ids": ("visible",),
        }),
        "missing": make_claim().model_copy(update={
            "claim_id": "missing", "evidence_chunk_ids": ("evidence",),
        }),
    }
    item = make_case(required_claim_ids=["known", "missing"],
                     missing_claim_ids=missing_ids, evidence_chunk_ids=["visible", "evidence"])
    assert "local_partial_invalid_missing_partition" in {
        issue.code for issue in validate_case(item, environment, chunks, claims)
    }
    valid = item.model_copy(update={"missing_claim_ids": ("missing",)})
    assert "local_partial_invalid_missing_partition" not in {
        issue.code for issue in validate_case(valid, environment, chunks, claims)
    }


@pytest.mark.parametrize("missing_ids", [[], ["claim1"]])
def test_local_missing_requires_all_required_claims_missing(missing_ids):
    case, environment, chunks, claims = valid_data()
    invalid = make_case(category="local_missing", required_claim_ids=["claim1", "known"],
                        missing_claim_ids=missing_ids)
    assert "local_missing_invalid_missing_partition" in {
        issue.code for issue in validate_case(invalid, environment, chunks, claims)
    }
    valid = make_case(category="local_missing", required_claim_ids=["claim1"],
                      missing_claim_ids=["claim1"])
    assert "local_missing_invalid_missing_partition" not in {
        issue.code for issue in validate_case(valid, environment, chunks, claims)
    }


def test_outdated_requires_expired_visible_conflict_and_research_current_claim():
    case, environment, chunks, claims = valid_data()
    outdated = make_case(category="outdated")
    assert "outdated_evidence_missing" in {
        issue.code for issue in validate_case(outdated, environment, chunks, claims)
    }
    chunks["visible"] = chunks["visible"].model_copy(update={"claim_ids": ("old",)})
    claims["old"] = make_claim().model_copy(update={
        "claim_id": "old", "evidence_chunk_ids": ("visible",),
        "valid_until": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "conflicts_with": ("claim1",),
    })
    assert "outdated_evidence_missing" not in {
        issue.code for issue in validate_case(outdated, environment, chunks, claims)
    }


def test_conflict_requires_visible_conflict_pair_and_research_adjudication():
    case, environment, chunks, claims = valid_data()
    conflict = make_case(category="conflict")
    assert "conflict_evidence_missing" in {
        issue.code for issue in validate_case(conflict, environment, chunks, claims)
    }
    chunks["visible"] = chunks["visible"].model_copy(update={"claim_ids": ("left", "right")})
    claims.update({
        "left": make_claim().model_copy(update={
            "claim_id": "left", "evidence_chunk_ids": ("visible",),
            "conflicts_with": ("right",),
        }),
        "right": make_claim().model_copy(update={
            "claim_id": "right", "evidence_chunk_ids": ("visible",),
            "conflicts_with": (),
        }),
    })
    assert "conflict_evidence_missing" not in {
        issue.code for issue in validate_case(conflict, environment, chunks, claims)
    }


def test_repeated_knowledge_adds_no_category_specific_issue():
    case, environment, chunks, claims = valid_data()
    repeated = make_case(category="repeated_knowledge")
    codes = {issue.code for issue in validate_case(repeated, environment, chunks, claims)}
    assert not {code for code in codes if code.startswith("repeated_knowledge_")}


def test_validate_case_sorts_issues_deterministically():
    case, environment, chunks, claims = valid_data()
    broken = make_case(evidence_chunk_ids=["unknown", "excluded"])
    issues = validate_case(broken, environment, chunks, claims)
    assert issues == tuple(sorted(
        issues, key=lambda issue: (issue.case_id or "", issue.code, issue.refs, issue.message)
    ))


def test_runtime_payload_has_no_label_or_audit_fields():
    case, environment, _, _ = valid_data()
    payload = build_runtime_payload(case, environment)
    assert set(payload) == {
        "case_id", "base_question_id", "question", "environment_id", "visible_chunk_ids",
    }
    assert LABEL_FIELDS.isdisjoint(payload)
    assert {"category", "local_knowledge_ids", "answer_key", "required_claim_ids",
            "missing_claim_ids", "evidence_chunk_ids",
            "annotation_reason", "draft_status", "review_status", "human_review_status"} <= LABEL_FIELDS


def test_validate_dataset_reports_duplicate_keys_and_missing_environment():
    case, environment, chunks, claims = valid_data()
    duplicate = case.model_copy(update={"environment_id": "unknown"})
    issues = validate_dataset((case, duplicate), (environment, environment),
                              tuple(chunks.values()), tuple(claims.values()))
    assert {issue.code for issue in issues} >= {
        "duplicate_case_id", "duplicate_environment_id", "environment_not_found",
    }


def test_validate_dataset_reports_broken_corpus_relationships():
    case, environment, chunks, claims = valid_data()
    chunks["visible"] = chunks["visible"].model_copy(update={"claim_ids": ("unknown",)})
    claims["claim1"] = claims["claim1"].model_copy(
        update={"evidence_chunk_ids": ("unknown-chunk",)}
    )
    issues = validate_dataset((case,), (environment,), tuple(chunks.values()), tuple(claims.values()))
    assert {issue.code for issue in issues} >= {
        "chunk_claim_not_found", "claim_evidence_chunk_not_found",
    }


def test_validate_dataset_reports_asymmetric_chunk_claim_relationships():
    case, environment, chunks, claims = valid_data()
    chunks["visible"] = chunks["visible"].model_copy(update={"claim_ids": ("claim1",)})
    issues = validate_dataset((case,), (environment,), tuple(chunks.values()), tuple(claims.values()))
    assert "chunk_claim_missing_evidence_link" in {issue.code for issue in issues}

    chunks["visible"] = chunks["visible"].model_copy(update={"claim_ids": ()})
    claims["claim1"] = claims["claim1"].model_copy(update={"evidence_chunk_ids": ("visible",)})
    issues = validate_dataset((case,), (environment,), tuple(chunks.values()), tuple(claims.values()))
    assert "claim_evidence_missing_claim_link" in {issue.code for issue in issues}


def test_validate_dataset_reports_unknown_conflict_claim():
    case, environment, chunks, claims = valid_data()
    claims["claim1"] = claims["claim1"].model_copy(update={"conflicts_with": ("unknown",)})
    issues = validate_dataset((case,), (environment,), tuple(chunks.values()), tuple(claims.values()))
    assert "claim_conflict_not_found" in {issue.code for issue in issues}


def test_validation_issue_order_is_independent_of_input_order():
    case, environment, chunks, claims = valid_data()
    duplicate = case.model_copy(update={"case_id": "z-case", "environment_id": "unknown"})
    forward = validate_dataset((case, duplicate), (environment,),
                               tuple(chunks.values()), tuple(claims.values()))
    backward = validate_dataset((duplicate, case), (environment,),
                                tuple(reversed(tuple(chunks.values()))),
                                tuple(reversed(tuple(claims.values()))))
    assert forward == backward
    assert forward == tuple(sorted(
        forward, key=lambda issue: (issue.case_id or "", issue.code, issue.refs, issue.message)
    ))


def test_duplicate_environment_selection_is_independent_of_input_order():
    case, environment, chunks, claims = valid_data()
    alternative = make_environment(visible_chunk_ids=["evidence"], research_chunk_ids=["visible"])
    forward = validate_dataset((case,), (environment, alternative),
                               tuple(chunks.values()), tuple(claims.values()))
    backward = validate_dataset((case,), (alternative, environment),
                                tuple(chunks.values()), tuple(claims.values()))
    assert forward == backward
