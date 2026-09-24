from datetime import datetime, timezone
from time import perf_counter

import pytest
from pydantic import ValidationError

import knowledge_gap_agent.benchmark.validation as validation_module
from knowledge_gap_agent.benchmark import (
    LABEL_FIELDS,
    KnowledgeEnvironment,
    build_model_input_payload,
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


def outdated_data(
    *,
    old_until: datetime | None,
    current_from: datetime | None,
    old_conflicts: tuple[str, ...] = ("claim1",),
    current_conflicts: tuple[str, ...] = ("old",),
):
    _, environment, chunks, claims = valid_data()
    target = make_case(category="outdated")
    chunks["visible"] = chunks["visible"].model_copy(update={"claim_ids": ("old",)})
    claims["old"] = make_claim().model_copy(update={
        "claim_id": "old",
        "evidence_chunk_ids": ("visible",),
        "valid_from": None,
        "valid_until": old_until,
        "conflicts_with": old_conflicts,
    })
    claims["claim1"] = claims["claim1"].model_copy(update={
        "valid_from": current_from,
        "valid_until": None,
        "conflicts_with": current_conflicts,
    })
    return target, environment, chunks, claims


def conflict_data(adjudicator_conflicts: tuple[str, ...]):
    _, environment, chunks, claims = valid_data()
    target = make_case(category="conflict")
    chunks["visible"] = chunks["visible"].model_copy(
        update={"claim_ids": ("left", "right")}
    )
    claims["left"] = make_claim().model_copy(update={
        "claim_id": "left",
        "evidence_chunk_ids": ("visible",),
        "conflicts_with": ("right",),
    })
    claims["right"] = make_claim().model_copy(update={
        "claim_id": "right",
        "evidence_chunk_ids": ("visible",),
        "conflicts_with": ("left",),
    })
    claims["claim1"] = claims["claim1"].model_copy(
        update={"conflicts_with": adjudicator_conflicts}
    )
    return target, environment, chunks, claims


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


@pytest.mark.parametrize(
    "old_until,current_from",
    [
        (None, datetime(2026, 1, 2, tzinfo=timezone.utc)),
        (datetime(2026, 1, 1, tzinfo=timezone.utc), None),
        (
            datetime(2026, 1, 2, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc),
        ),
        (
            datetime(2026, 1, 3, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc),
        ),
        (datetime(2026, 1, 1), datetime(2026, 1, 2, tzinfo=timezone.utc)),
        (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2)),
    ],
)
def test_outdated_requires_strict_timezone_aware_temporal_handoff(
    old_until: datetime | None,
    current_from: datetime | None,
) -> None:
    target, environment, chunks, claims = outdated_data(
        old_until=old_until,
        current_from=current_from,
    )

    codes = {issue.code for issue in validate_case(target, environment, chunks, claims)}

    assert "outdated_evidence_missing" in codes


def test_outdated_requires_direct_conflict_with_research_current_claim() -> None:
    target, environment, chunks, claims = outdated_data(
        old_until=datetime(2026, 1, 1, tzinfo=timezone.utc),
        current_from=datetime(2026, 1, 2, tzinfo=timezone.utc),
        old_conflicts=(),
        current_conflicts=(),
    )

    codes = {issue.code for issue in validate_case(target, environment, chunks, claims)}

    assert "outdated_evidence_missing" in codes


def test_outdated_accepts_direct_conflict_with_strict_temporal_handoff() -> None:
    target, environment, chunks, claims = outdated_data(
        old_until=datetime(2030, 1, 1, tzinfo=timezone.utc),
        current_from=datetime(2030, 1, 2, tzinfo=timezone.utc),
    )

    codes = {issue.code for issue in validate_case(target, environment, chunks, claims)}

    assert "outdated_evidence_missing" not in codes


def test_outdated_rejects_self_conflict_reusing_one_claim_for_both_roles() -> None:
    _, environment, chunks, claims = valid_data()
    target = make_case(category="outdated")
    chunks["visible"] = chunks["visible"].model_copy(
        update={"claim_ids": ("claim1",)}
    )
    claims["claim1"] = claims["claim1"].model_copy(update={
        "evidence_chunk_ids": ("visible", "evidence"),
        "valid_from": datetime(2026, 1, 2, tzinfo=timezone.utc),
        "valid_until": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "conflicts_with": ("claim1",),
    })

    codes = {issue.code for issue in validate_case(target, environment, chunks, claims)}

    assert "outdated_evidence_missing" in codes


def test_outdated_requires_time_and_conflict_on_the_same_claim_pair() -> None:
    target, environment, chunks, claims = outdated_data(
        old_until=datetime(2026, 1, 1, tzinfo=timezone.utc),
        current_from=datetime(2026, 1, 2, tzinfo=timezone.utc),
        old_conflicts=(),
        current_conflicts=("old-without-time",),
    )
    chunks["visible"] = chunks["visible"].model_copy(
        update={"claim_ids": ("old", "old-without-time")}
    )
    claims["old-without-time"] = claims["old"].model_copy(update={
        "claim_id": "old-without-time",
        "valid_until": None,
        "conflicts_with": ("claim1",),
    })

    codes = {issue.code for issue in validate_case(target, environment, chunks, claims)}

    assert "outdated_evidence_missing" in codes


@pytest.mark.parametrize(
    "old_conflicts,current_conflicts",
    [(("claim1",), ()), ((), ("old",))],
)
def test_outdated_accepts_one_way_conflict_in_either_direction(
    old_conflicts: tuple[str, ...],
    current_conflicts: tuple[str, ...],
) -> None:
    target, environment, chunks, claims = outdated_data(
        old_until=datetime(2026, 1, 1, tzinfo=timezone.utc),
        current_from=datetime(2026, 1, 2, tzinfo=timezone.utc),
        old_conflicts=old_conflicts,
        current_conflicts=current_conflicts,
    )

    codes = {issue.code for issue in validate_case(target, environment, chunks, claims)}

    assert "outdated_evidence_missing" not in codes


def test_conflict_adjudicator_must_link_both_visible_sides() -> None:
    target, environment, chunks, claims = conflict_data(
        adjudicator_conflicts=("left",)
    )

    codes = {issue.code for issue in validate_case(target, environment, chunks, claims)}

    assert "conflict_evidence_missing" in codes


def test_conflict_accepts_adjudicator_linked_to_both_visible_sides() -> None:
    target, environment, chunks, claims = conflict_data(
        adjudicator_conflicts=("left", "right")
    )

    codes = {issue.code for issue in validate_case(target, environment, chunks, claims)}

    assert "conflict_evidence_missing" not in codes


def test_conflict_rejects_visible_endpoint_reused_as_adjudicator() -> None:
    _, environment, chunks, claims = valid_data()
    target = make_case(
        category="conflict",
        required_claim_ids=["left"],
        missing_claim_ids=["left"],
    )
    chunks["visible"] = chunks["visible"].model_copy(
        update={"claim_ids": ("left", "right")}
    )
    chunks["evidence"] = chunks["evidence"].model_copy(
        update={"claim_ids": ("left",)}
    )
    claims = {
        "left": make_claim().model_copy(update={
            "claim_id": "left",
            "evidence_chunk_ids": ("visible", "evidence"),
            "conflicts_with": ("left", "right"),
        }),
        "right": make_claim().model_copy(update={
            "claim_id": "right",
            "evidence_chunk_ids": ("visible",),
            "conflicts_with": ("left",),
        }),
    }

    codes = {issue.code for issue in validate_case(target, environment, chunks, claims)}

    assert "conflict_evidence_missing" in codes


def test_conflict_rejects_two_adjudicators_each_linking_only_one_side() -> None:
    target, environment, chunks, claims = conflict_data(adjudicator_conflicts=())
    target = target.model_copy(update={
        "required_claim_ids": ("adjudicator-left", "adjudicator-right"),
        "missing_claim_ids": ("adjudicator-left", "adjudicator-right"),
    })
    chunks["evidence"] = chunks["evidence"].model_copy(
        update={"claim_ids": ("adjudicator-left", "adjudicator-right")}
    )
    del claims["claim1"]
    claims["adjudicator-left"] = make_claim().model_copy(update={
        "claim_id": "adjudicator-left",
        "conflicts_with": ("left",),
    })
    claims["adjudicator-right"] = make_claim().model_copy(update={
        "claim_id": "adjudicator-right",
        "conflicts_with": ("right",),
    })

    codes = {issue.code for issue in validate_case(target, environment, chunks, claims)}

    assert "conflict_evidence_missing" in codes


@pytest.mark.parametrize("reverse_edges", [False, True])
def test_conflict_accepts_one_way_edges_in_either_direction(
    reverse_edges: bool,
) -> None:
    target, environment, chunks, claims = conflict_data(
        adjudicator_conflicts=("left", "right")
    )
    if reverse_edges:
        claims["left"] = claims["left"].model_copy(
            update={"conflicts_with": ("claim1",)}
        )
        claims["right"] = claims["right"].model_copy(
            update={"conflicts_with": ("left", "claim1")}
        )
        claims["claim1"] = claims["claim1"].model_copy(
            update={"conflicts_with": ()}
        )
    else:
        claims["right"] = claims["right"].model_copy(update={"conflicts_with": ()})

    codes = {issue.code for issue in validate_case(target, environment, chunks, claims)}

    assert "conflict_evidence_missing" not in codes


def test_conflict_neighbors_are_undirected_and_ignore_self_and_unknown() -> None:
    build_neighbors = getattr(validation_module, "_conflict_neighbors", None)
    assert build_neighbors is not None
    claims = {
        "left": make_claim().model_copy(update={
            "claim_id": "left",
            "conflicts_with": ("left", "right", "unknown"),
        }),
        "right": make_claim().model_copy(update={
            "claim_id": "right",
            "conflicts_with": (),
        }),
    }

    assert build_neighbors(claims) == {
        "left": frozenset({"right"}),
        "right": frozenset({"left"}),
    }


def test_conflict_neighbors_do_not_rescan_declared_conflict_tuples() -> None:
    contains_calls = 0

    class CountingConflicts(tuple):
        def __contains__(self, item: object) -> bool:
            nonlocal contains_calls
            contains_calls += 1
            return super().__contains__(item)

    declared = CountingConflicts(("right",))
    claims = {
        "left": make_claim().model_copy(update={
            "claim_id": "left",
            "conflicts_with": declared,
        }),
        "right": make_claim().model_copy(update={
            "claim_id": "right",
            "conflicts_with": (),
        }),
    }

    neighbors = validation_module._conflict_neighbors(claims)

    assert neighbors["left"] == frozenset({"right"})
    assert contains_calls == 0


def test_bipartite_conflict_search_uses_constant_time_research_intersection() -> None:
    has_adjudicated_conflict = getattr(
        validation_module, "_has_adjudicated_visible_conflict", None
    )
    assert has_adjudicated_conflict is not None
    contains_calls = 0

    class CountingNeighbors(frozenset):
        def __contains__(self, item: object) -> bool:
            nonlocal contains_calls
            contains_calls += 1
            return super().__contains__(item)

        def __and__(self, other: object):
            return CountingNeighbors(super().__and__(other))

        def __sub__(self, other: object):
            return CountingNeighbors(super().__sub__(other))

    def bipartite_without_witness(
        partition_size: int,
        neighbor_type=CountingNeighbors,
    ):
        left = {f"left-{index:03d}" for index in range(partition_size)}
        right = {f"right-{index:03d}" for index in range(partition_size)}
        left_research = {
            f"left-research-{index:03d}" for index in range(partition_size)
        }
        right_research = {
            f"right-research-{index:03d}" for index in range(partition_size)
        }
        neighbors = {}
        for visible_id in left:
            neighbors[visible_id] = neighbor_type(right | left_research)
        for visible_id in right:
            neighbors[visible_id] = neighbor_type(left | right_research)
        for research_id in left_research:
            neighbors[research_id] = neighbor_type(left)
        for research_id in right_research:
            neighbors[research_id] = neighbor_type(right)
        return left | right, left_research | right_research, neighbors

    def membership_checks(partition_size: int) -> int:
        nonlocal contains_calls
        contains_calls = 0
        visible, research, neighbors = bipartite_without_witness(partition_size)

        assert not has_adjudicated_conflict(visible, research, neighbors)
        return contains_calls

    small_count = membership_checks(15)
    large_count = membership_checks(30)

    assert small_count > 0
    assert large_count <= small_count * 5

    visible, research, neighbors = bipartite_without_witness(200, frozenset)
    started_at = perf_counter()
    assert not has_adjudicated_conflict(visible, research, neighbors)
    elapsed = perf_counter() - started_at
    assert elapsed < 2.0


def test_outdated_search_scales_with_edges_without_tuple_membership_scans() -> None:
    equality_checks = 0

    class CountingConflictRef(str):
        def __eq__(self, other: object) -> bool:
            nonlocal equality_checks
            equality_checks += 1
            return super().__eq__(other)

        __hash__ = str.__hash__

    def dense_equal_time_case(size: int) -> int:
        nonlocal equality_checks
        visible_chunk_ids = [f"visible-{index:03d}" for index in range(size)]
        research_chunk_ids = [f"research-{index:03d}" for index in range(size)]
        old_claim_ids = [f"old-{index:03d}" for index in range(size)]
        current_claim_ids = [f"current-{index:03d}" for index in range(size)]
        environment = make_environment(
            visible_chunk_ids=visible_chunk_ids,
            research_chunk_ids=research_chunk_ids,
        )
        chunks = {
            chunk.chunk_id: chunk
            for chunk in (
                *(
                    make_chunk(chunk_id, (claim_id,))
                    for chunk_id, claim_id in zip(visible_chunk_ids, old_claim_ids)
                ),
                *(
                    make_chunk(chunk_id, (claim_id,))
                    for chunk_id, claim_id in zip(research_chunk_ids, current_claim_ids)
                ),
                make_chunk("excluded", ()),
            )
        }
        equal_time = datetime(2026, 1, 2, tzinfo=timezone.utc)
        conflict_refs = tuple(CountingConflictRef(item) for item in current_claim_ids)
        claims = {
            claim_id: make_claim().model_copy(update={
                "claim_id": claim_id,
                "evidence_chunk_ids": (chunk_id,),
                "valid_from": None,
                "valid_until": equal_time,
                "conflicts_with": conflict_refs,
            })
            for chunk_id, claim_id in zip(visible_chunk_ids, old_claim_ids)
        }
        claims.update({
            claim_id: make_claim().model_copy(update={
                "claim_id": claim_id,
                "evidence_chunk_ids": (chunk_id,),
                "valid_from": equal_time,
                "conflicts_with": (),
            })
            for chunk_id, claim_id in zip(research_chunk_ids, current_claim_ids)
        })
        target = make_case(category="outdated").model_copy(update={
            "required_claim_ids": tuple(current_claim_ids),
            "missing_claim_ids": tuple(current_claim_ids),
            "evidence_chunk_ids": tuple(research_chunk_ids),
        })
        equality_checks = 0

        codes = {
            issue.code for issue in validate_case(target, environment, chunks, claims)
        }

        assert "outdated_evidence_missing" in codes
        return equality_checks

    small_count = dense_equal_time_case(12)
    large_count = dense_equal_time_case(24)

    assert small_count > 0
    assert large_count <= small_count * 5


def test_conflict_unknown_links_do_not_crash_or_replace_two_sided_adjudication() -> None:
    target, environment, chunks, claims = conflict_data(
        adjudicator_conflicts=("left", "right", "unknown")
    )
    claims["left"] = claims["left"].model_copy(
        update={"conflicts_with": ("right", "unknown")}
    )

    codes = {issue.code for issue in validate_case(target, environment, chunks, claims)}

    assert "conflict_evidence_missing" not in codes


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


def test_model_input_payload_contains_only_question_and_visible_text_in_environment_order():
    case = make_case(question="如何处理？")
    environment = make_environment(
        visible_chunk_ids=["a-visible", "b-visible"],
        research_chunk_ids=["research"],
        excluded_chunk_ids=["excluded"],
    )
    chunks = (
        make_chunk("b-visible", ()),
        make_chunk("excluded", ()),
        make_chunk("a-visible", ()),
        make_chunk("research", ()),
    )

    assert build_model_input_payload(case, environment, chunks) == {
        "question": "如何处理？",
        "visible_knowledge": ["text-a-visible", "text-b-visible"],
    }


def test_model_input_payload_rejects_unknown_and_duplicate_chunk_references():
    case = make_case()
    chunks = (make_chunk("visible", ()),)

    with pytest.raises(ValueError, match="visible chunk.*missing"):
        build_model_input_payload(case, make_environment(visible_chunk_ids=["missing"]), chunks)

    duplicate_reference = make_environment().model_copy(
        update={"visible_chunk_ids": ("visible", "visible")}
    )
    with pytest.raises(ValueError, match="duplicate"):
        build_model_input_payload(case, duplicate_reference, chunks)

    with pytest.raises(ValueError, match="duplicate corpus chunk id"):
        build_model_input_payload(case, make_environment(), (chunks[0], chunks[0]))


def test_model_input_payload_revalidates_case_environment_and_chunks():
    case = make_case()
    environment = make_environment()
    chunks = (make_chunk("visible", ()),)

    wrong_environment = make_environment(environment_id="other-environment")
    with pytest.raises(ValueError, match="case environment does not match"):
        build_model_input_payload(case, wrong_environment, chunks)

    tampered_chunk = chunks[0].model_copy(update={"text": "篡改后仍保留旧哈希"})
    with pytest.raises(ValidationError, match="content_hash"):
        build_model_input_payload(case, environment, (tampered_chunk,))

    empty_question = case.model_copy(update={"question": ""})
    with pytest.raises(ValidationError, match="question"):
        build_model_input_payload(empty_question, environment, chunks)


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
