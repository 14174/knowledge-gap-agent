import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from knowledge_gap_agent.benchmark import (
    HumanReviewDecision,
    HumanReviewRecord,
    LABEL_FIELDS,
    KnowledgeEnvironment,
    ReviewDecision,
    ReviewRecord,
    compute_environment_hash,
    compute_review_target_hash,
)
from knowledge_gap_agent.benchmark.freeze import freeze_benchmark as freeze_with_corpus
from knowledge_gap_agent.contracts.benchmark import (
    BenchmarkCase,
    CaseCategory,
    DraftStatus,
    HumanReviewStatus,
    ReviewStatus,
)
from knowledge_gap_agent.corpus.models import Claim, CorpusChunk
from knowledge_gap_agent.corpus.normalize import content_hash


def environment(case_id: str = "case-b") -> KnowledgeEnvironment:
    environment_id = f"env-{case_id}"
    return KnowledgeEnvironment(
        environment_id=environment_id,
        visible_chunk_ids=[f"chunk-{case_id}"],
        research_chunk_ids=[], excluded_chunk_ids=[],
        environment_hash=compute_environment_hash(
            environment_id, [f"chunk-{case_id}"], [], []
        ),
    )


def case(case_id: str = "case-b", **overrides: object) -> BenchmarkCase:
    values = {
        "case_id": case_id, "base_question_id": f"q-{case_id}", "question": "问题",
        "category": "local_sufficient", "annotation_reason": "证据完整",
        "required_claims": ["主张"], "allowed_source_ids": ["source"],
        "answer_key": ["答案"], "local_knowledge_ids": [f"chunk-{case_id}"],
        "need_research": False, "environment_id": f"env-{case_id}",
        "required_claim_ids": [f"claim-{case_id}"], "missing_claim_ids": [],
        "evidence_chunk_ids": [f"chunk-{case_id}"], "draft_status": "validated",
        "review_status": "approved", "human_review_status": "not_required",
    }
    values.update(overrides)
    return BenchmarkCase(**values)


def corpus_for_pairs(
    pairs: list[tuple[BenchmarkCase, KnowledgeEnvironment]]
    | tuple[tuple[BenchmarkCase, KnowledgeEnvironment], ...],
) -> tuple[tuple[CorpusChunk, ...], tuple[Claim, ...]]:
    chunks: dict[str, CorpusChunk] = {}
    claims: dict[str, Claim] = {}
    for target_case, target_environment in pairs:
        for chunk_id in (
            target_environment.visible_chunk_ids
            + target_environment.research_chunk_ids
            + target_environment.excluded_chunk_ids
        ):
            text = f"正文 {chunk_id}"
            chunks[chunk_id] = CorpusChunk(
                chunk_id=chunk_id,
                source_id="source",
                heading_path=("标题",),
                start_line=1,
                end_line=1,
                text=text,
                token_terms=(),
                content_hash=content_hash(text),
                claim_ids=(
                    target_case.required_claim_ids
                    if chunk_id in target_case.evidence_chunk_ids
                    else ()
                ),
            )
        for claim_id in target_case.required_claim_ids:
            claims[claim_id] = Claim(
                claim_id=claim_id,
                statement="主张",
                evidence_chunk_ids=target_case.evidence_chunk_ids,
                valid_from=None,
                valid_until=None,
                conflicts_with=(),
            )
    return tuple(chunks.values()), tuple(claims.values())


def freeze_benchmark(
    cases: object,
    reviews: object,
    output_dir: Path,
    require_human_approval: bool = True,
    *,
    human_reviews: object = (),
):
    values = tuple(cases.values()) if isinstance(cases, dict) else tuple(cases)
    chunks, claims = corpus_for_pairs(values)
    return freeze_with_corpus(
        cases,
        reviews,
        chunks,
        claims,
        output_dir,
        require_human_approval,
        human_reviews=human_reviews,
    )


def review(
    case_id: str = "case-b",
    *,
    target_case: BenchmarkCase | None = None,
    target_environment: KnowledgeEnvironment | None = None,
    **overrides: object,
) -> ReviewRecord:
    target_case = target_case or case(case_id)
    target_environment = target_environment or environment(case_id)
    chunks, claims = corpus_for_pairs([(target_case, target_environment)])
    values = {
        "case_id": case_id, "decision": ReviewDecision.APPROVE, "issues": [],
        "review_target_hash": compute_review_target_hash(
            target_case, target_environment, chunks, claims
        ),
        "suggested_changes": [], "evidence_refs": [f"chunk-{case_id}"],
        "reviewer_confidence": 0.9, "labeler_reasoning_seen": False,
        "prior_rule_failure_count": 0, "prompt_version": "v1", "prompt_hash": "a" * 64,
        "model_provider": "local", "model_name": "reviewer", "model_revision": "r1",
        "reviewed_at": datetime(2026, 9, 24, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return ReviewRecord(**values)


def human_review(
    target_case: BenchmarkCase,
    target_review: ReviewRecord,
    **overrides: object,
) -> HumanReviewRecord:
    values = {
        "case_id": target_case.case_id,
        "review_target_hash": target_review.review_target_hash,
        "decision": HumanReviewDecision.APPROVED,
        "actor": "human-reviewer",
        "reason": "标签、问题、答案键和三池关系一致。",
        "reviewed_at": datetime(2026, 9, 25, tzinfo=timezone.utc),
        "requested_changes": (),
    }
    values.update(overrides)
    return HumanReviewRecord(**values)


def high_risk_bundle(
    case_id: str = "case-b",
    *,
    human_review_status: str = "pending",
) -> tuple[BenchmarkCase, KnowledgeEnvironment, ReviewRecord, HumanReviewRecord]:
    target_case = case(
        case_id,
        category="conflict",
        need_research=True,
        human_review_status=human_review_status,
    )
    target_environment = environment(case_id)
    model_review = review(
        case_id,
        target_case=target_case,
        target_environment=target_environment,
    )
    return (
        target_case,
        target_environment,
        model_review,
        human_review(target_case, model_review),
    )


def test_freeze_rejects_review_when_case_or_environment_changed(tmp_path: Path) -> None:
    original_case = case()
    original_environment = environment()
    bound_review = review(target_case=original_case, target_environment=original_environment)
    changed_cases = (
        original_case.model_copy(update={"question": "新问题"}),
        original_case.model_copy(update={"answer_key": ("新答案",)}),
        original_case.model_copy(update={"category": CaseCategory.REPEATED_KNOWLEDGE}),
        original_case.model_copy(update={"draft_status": DraftStatus.GENERATED}),
    )

    for changed in changed_cases:
        with pytest.raises(ValueError, match="review_target_hash"):
            freeze_benchmark(
                [(changed, original_environment)], [bound_review], tmp_path,
                require_human_approval=False,
            )
    changed_environment = environment().model_copy(update={
        "visible_chunk_ids": ("changed",),
        "environment_hash": compute_environment_hash(
            original_environment.environment_id, ("changed",), (), ()
        ),
    })
    with pytest.raises(ValueError, match="review_target_hash"):
        freeze_benchmark(
            [(original_case, changed_environment)], [bound_review], tmp_path,
            require_human_approval=False,
        )
    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


def test_freeze_rejects_old_review_after_reviewer_visible_chunk_changes(
    tmp_path: Path,
) -> None:
    target_case = case()
    target_environment = environment()
    chunks, claims = corpus_for_pairs([(target_case, target_environment)])
    bound_review = review(
        target_case=target_case,
        target_environment=target_environment,
    )
    original = chunks[0]
    changed_text = f"{original.text} 已变更"
    changed_chunk = original.model_copy(update={
        "text": changed_text,
        "content_hash": content_hash(changed_text),
    })

    with pytest.raises(ValueError, match="review_target_hash"):
        freeze_with_corpus(
            [(target_case, target_environment)],
            [bound_review],
            (changed_chunk,),
            claims,
            tmp_path,
        )

    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


def read_jsonl(path: Path) -> list[dict]:
    raw = path.read_bytes()
    assert raw.endswith(b"\n") and b"\r\n" not in raw
    lines = raw.decode("utf-8").splitlines()
    return [json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            for line in lines]


def test_freeze_separates_runtime_labels_and_audit_and_is_stable(tmp_path: Path) -> None:
    pairs = [(case("case-b", human_review_status="approved"), environment("case-b")),
             (case("case-a", human_review_status="approved"), environment("case-a"))]
    reviews = [
        review(
            "case-b",
            target_case=pairs[0][0].model_copy(update={
                "review_status": ReviewStatus.PENDING,
                "human_review_status": HumanReviewStatus.NOT_REQUIRED,
            }),
            target_environment=pairs[0][1],
            prior_rule_failure_count=1,
        ),
        review(
            "case-a",
            target_case=pairs[1][0].model_copy(update={
                "review_status": ReviewStatus.PENDING,
                "human_review_status": HumanReviewStatus.NOT_REQUIRED,
            }),
            target_environment=pairs[1][1],
            prior_rule_failure_count=1,
        ),
    ]
    human_reviews = [
        human_review(pairs[0][0], reviews[0]),
        human_review(pairs[1][0], reviews[1]),
    ]
    first = freeze_benchmark(
        pairs, reviews, tmp_path, human_reviews=human_reviews
    )

    runtime = read_jsonl(first.runtime_path)
    labels = read_jsonl(first.labels_path)
    audit = read_jsonl(first.audit_path)
    assert [row["case_id"] for row in runtime] == ["case-a", "case-b"]
    assert all(LABEL_FIELDS.isdisjoint(row) for row in runtime)
    assert set(labels[0]) == {
        "case_id", "category", "need_research", "required_claim_ids",
        "missing_claim_ids", "evidence_chunk_ids", "answer_key",
    }
    assert set(audit[0]) == {"case", "review", "human_review"}
    assert audit[0]["case"]["annotation_reason"] == "证据完整"
    assert audit[0]["review"]["prior_rule_failure_count"] == 1
    assert audit[0]["human_review"] == human_reviews[1].model_dump(mode="json")
    assert all("human_review" not in row for row in runtime)
    assert all("human_review" not in row for row in labels)
    assert first.case_count == 2
    assert all(len(value) == 64 for value in (
        first.runtime_hash, first.labels_hash, first.audit_hash, first.dataset_hash
    ))

    second = freeze_benchmark(
        {"z": pairs[1], "a": pairs[0]},
        {"z": reviews[1], "a": reviews[0]},
        tmp_path,
        human_reviews={"z": human_reviews[1], "a": human_reviews[0]},
    )
    assert second == first


def test_forged_case_approval_cannot_replace_human_record(tmp_path: Path) -> None:
    target_case = case(
        category="outdated",
        need_research=True,
        human_review_status="approved",
    )
    target_environment = environment()
    model_review = review(
        target_case=target_case,
        target_environment=target_environment,
    )
    with pytest.raises(ValueError, match="missing human review"):
        freeze_benchmark(
            [(target_case, target_environment)],
            [model_review],
            tmp_path,
            human_reviews=[],
        )
    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("kind", ["duplicate", "extra"])
def test_formal_freeze_requires_exact_human_review_case_set(
    tmp_path: Path, kind: str
) -> None:
    target_case, target_environment, model_review, approval = high_risk_bundle()
    records = [approval, approval]
    if kind == "extra":
        other_case, _, other_review, other_approval = high_risk_bundle("case-extra")
        assert other_case.case_id == other_review.case_id
        records = [approval, other_approval]

    with pytest.raises(ValueError, match=f"{kind} human review"):
        freeze_benchmark(
            [(target_case, target_environment)],
            [model_review],
            tmp_path,
            human_reviews=records,
        )

    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


def test_formal_freeze_rejects_stale_human_review_target_without_writes(
    tmp_path: Path,
) -> None:
    target_case, target_environment, model_review, approval = high_risk_bundle()
    stale = approval.model_copy(update={"review_target_hash": "0" * 64})

    with pytest.raises(ValueError, match="human review_target_hash"):
        freeze_benchmark(
            [(target_case, target_environment)],
            [model_review],
            tmp_path,
            human_reviews=[stale],
        )

    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("decision", "requested_changes"),
    [
        (HumanReviewDecision.REVISE, ("补充当前证据",)),
        (HumanReviewDecision.REJECTED, ()),
    ],
)
def test_formal_freeze_rejects_nonapproval_human_decisions_without_writes(
    tmp_path: Path,
    decision: HumanReviewDecision,
    requested_changes: tuple[str, ...],
) -> None:
    target_case, target_environment, model_review, approval = high_risk_bundle()
    record = approval.model_copy(update={
        "decision": decision,
        "requested_changes": requested_changes,
    })

    with pytest.raises(ValueError, match="human review decision"):
        freeze_benchmark(
            [(target_case, target_environment)],
            [model_review],
            tmp_path,
            human_reviews=[record],
        )

    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


def test_formal_freeze_revalidates_bypassed_human_review_model(
    tmp_path: Path,
) -> None:
    target_case, target_environment, model_review, approval = high_risk_bundle()
    bypassed = HumanReviewRecord.model_construct(
        **{**approval.model_dump(mode="python"), "actor": "   "}
    )

    with pytest.raises(ValidationError, match="actor"):
        freeze_benchmark(
            [(target_case, target_environment)],
            [model_review],
            tmp_path,
            human_reviews=[bypassed],
        )

    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


def test_formal_freeze_derives_status_and_embeds_full_human_review_only_in_audit(
    tmp_path: Path,
) -> None:
    target_case, target_environment, model_review, approval = high_risk_bundle()

    result = freeze_benchmark(
        [(target_case, target_environment)],
        [model_review],
        tmp_path,
        human_reviews=[approval],
    )

    runtime = read_jsonl(result.runtime_path)
    labels = read_jsonl(result.labels_path)
    audit = read_jsonl(result.audit_path)
    assert audit == [{
        "case": target_case.model_copy(update={
            "review_status": ReviewStatus.APPROVED,
            "human_review_status": HumanReviewStatus.APPROVED,
        }).model_dump(mode="json"),
        "review": model_review.model_dump(mode="json"),
        "human_review": approval.model_dump(mode="json"),
    }]
    assert all("human_review" not in row for row in runtime)
    assert all("human_review" not in row for row in labels)
    for payload in (runtime, labels):
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        assert approval.actor not in encoded
        assert approval.reason not in encoded
        assert approval.reviewed_at.isoformat() not in encoded


def test_formal_freeze_rejects_terminal_case_status_that_disagrees_with_record(
    tmp_path: Path,
) -> None:
    target_case, target_environment, model_review, approval = high_risk_bundle(
        human_review_status="rejected"
    )

    with pytest.raises(ValueError, match="human_review_status disagrees"):
        freeze_benchmark(
            [(target_case, target_environment)],
            [model_review],
            tmp_path,
            human_reviews=[approval],
        )

    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


def test_candidate_freeze_rejects_nonempty_human_reviews(tmp_path: Path) -> None:
    target_case, target_environment, model_review, approval = high_risk_bundle()

    with pytest.raises(ValueError, match="candidate freeze.*human review"):
        freeze_benchmark(
            [(target_case, target_environment)],
            [model_review],
            tmp_path,
            require_human_approval=False,
            human_reviews=[approval],
        )

    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


def test_candidate_freeze_derives_nonfinal_human_status(tmp_path: Path) -> None:
    target_case = case(human_review_status="pending")
    target_environment = environment()
    result = freeze_benchmark(
        [(target_case, target_environment)],
        [review(target_case=target_case, target_environment=target_environment)],
        tmp_path,
        require_human_approval=False,
    )
    audit_row = read_jsonl(result.audit_path)[0]
    assert audit_row["case"]["human_review_status"] == "not_required"
    assert audit_row["human_review"] is None


def test_formal_freeze_derives_nonrequired_status_without_human_record(
    tmp_path: Path,
) -> None:
    target_case = case(review_status="pending", human_review_status="pending")
    target_environment = environment()
    model_review = review(
        target_case=target_case,
        target_environment=target_environment,
    )

    result = freeze_benchmark(
        [(target_case, target_environment)],
        [model_review],
        tmp_path,
        human_reviews=[],
    )

    audit_row = read_jsonl(result.audit_path)[0]
    assert audit_row["case"]["review_status"] == "approved"
    assert audit_row["case"]["human_review_status"] == "not_required"
    assert audit_row["human_review"] is None


@pytest.mark.parametrize("kind", ["missing", "extra", "duplicate"])
def test_case_review_relationship_must_be_one_to_one(tmp_path: Path, kind: str) -> None:
    pairs = [(case(), environment())]
    reviews = [] if kind == "missing" else [review("other")]
    if kind == "duplicate":
        reviews = [review(), review()]
    with pytest.raises(ValueError, match="review|重复|duplicate"):
        freeze_benchmark(pairs, reviews, tmp_path)
    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


def test_entry_point_revalidates_bypassed_models(tmp_path: Path) -> None:
    invalid = review().model_copy(update={"reviewer_confidence": math.nan})
    with pytest.raises(ValidationError, match="reviewer_confidence"):
        freeze_benchmark([(case(), environment())], [invalid], tmp_path)
    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("formal", [True, False])
def test_freeze_rejects_review_evidence_outside_case_even_when_model_constructed(
    tmp_path: Path, formal: bool
) -> None:
    bypassed = ReviewRecord.model_construct(**{
        **review().model_dump(), "evidence_refs": ("unknown-b", "unknown-a"),
    })
    with pytest.raises(ValueError, match=r"case-b.*evidence_refs.*unknown-a.*unknown-b"):
        freeze_benchmark(
            [(case(), environment())], [bypassed], tmp_path,
            require_human_approval=formal,
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure_call", [1, 2, 3])
def test_atomic_failure_leaves_no_formal_or_temporary_files(
    tmp_path: Path, monkeypatch, failure_call: int
) -> None:
    import knowledge_gap_agent.benchmark.freeze as module

    real_commit = module._commit
    calls = 0

    def fail_commit(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == failure_call:
            raise OSError("injected replace failure")
        real_commit(source, target)

    monkeypatch.setattr(module, "_commit", fail_commit)
    with pytest.raises(OSError, match="injected"):
        freeze_benchmark([(case(), environment())], [review()], tmp_path)
    assert not list(tmp_path.glob("benchmark-v0.1.*.jsonl"))
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_rollback_preserves_preexisting_identical_file(tmp_path: Path, monkeypatch) -> None:
    import knowledge_gap_agent.benchmark.freeze as module

    first = freeze_benchmark([(case(), environment())], [review()], tmp_path)
    runtime_content = first.runtime_path.read_bytes()
    first.labels_path.unlink()
    first.audit_path.unlink()

    def fail_commit(source: Path, target: Path) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(module, "_commit", fail_commit)
    with pytest.raises(OSError, match="injected"):
        freeze_benchmark([(case(), environment())], [review()], tmp_path)
    assert first.runtime_path.read_bytes() == runtime_content
    assert not first.labels_path.exists()
    assert not first.audit_path.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_existing_lock_rejects_without_writing(tmp_path: Path) -> None:
    lock = tmp_path / ".benchmark-v0.1.freeze.lock"
    lock.write_text("other transaction", encoding="utf-8")
    with pytest.raises(BlockingIOError):
        freeze_benchmark([(case(), environment())], [review()], tmp_path)
    assert list(tmp_path.iterdir()) == [lock]
    assert lock.read_text(encoding="utf-8") == "other transaction"


def test_commit_race_does_not_overwrite_concurrent_target(tmp_path: Path, monkeypatch) -> None:
    import knowledge_gap_agent.benchmark.freeze as module

    real_commit = module._commit
    calls = 0

    def race_commit(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            target.write_bytes(b"concurrent\n")
        real_commit(source, target)

    monkeypatch.setattr(module, "_commit", race_commit)
    with pytest.raises(FileExistsError):
        freeze_benchmark([(case(), environment())], [review()], tmp_path)
    runtime = tmp_path / "benchmark-v0.1.runtime.jsonl"
    assert runtime.read_bytes() == b"concurrent\n"
    assert not (tmp_path / ".benchmark-v0.1.freeze.lock").exists()


def test_rollback_preserves_first_target_replaced_by_external_content(
    tmp_path: Path, monkeypatch
) -> None:
    import knowledge_gap_agent.benchmark.freeze as module

    real_commit = module._commit
    calls = 0
    first_target: Path | None = None

    def injected_commit(source: Path, target: Path) -> None:
        nonlocal calls, first_target
        calls += 1
        if calls == 1:
            real_commit(source, target)
            first_target = target
            return
        assert first_target is not None
        first_target.unlink()
        first_target.write_bytes(b"external replacement\n")
        raise OSError("second commit failed")

    monkeypatch.setattr(module, "_commit", injected_commit)
    with pytest.raises(OSError, match="second commit"):
        freeze_benchmark([(case(), environment())], [review()], tmp_path)
    assert first_target is not None
    assert first_target.read_bytes() == b"external replacement\n"
    assert not (tmp_path / ".benchmark-v0.1.freeze.lock").exists()


def test_temp_unlink_failure_after_link_rolls_back_target_temp_and_lock(
    tmp_path: Path, monkeypatch
) -> None:
    original_unlink = Path.unlink
    failed_once = False

    def fail_first_temp_unlink(path: Path, *args, **kwargs) -> None:
        nonlocal failed_once
        if path.suffix == ".tmp" and not failed_once:
            failed_once = True
            raise OSError("injected temp unlink failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_first_temp_unlink)
    with pytest.raises(OSError, match="temp unlink"):
        freeze_benchmark([(case(), environment())], [review()], tmp_path)
    assert not list(tmp_path.glob("benchmark-v0.1.*.jsonl"))
    assert not list(tmp_path.glob("*.tmp"))
    assert not (tmp_path / ".benchmark-v0.1.freeze.lock").exists()


def test_cleanup_continues_but_preserves_lock_and_primary_error_when_owned_file_is_busy(
    tmp_path: Path, monkeypatch
) -> None:
    import knowledge_gap_agent.benchmark.freeze as module

    real_commit = module._commit
    real_unlink = Path.unlink
    commit_calls = 0
    attempted_owned_cleanup: list[str] = []

    def fail_third_commit(source: Path, target: Path) -> None:
        nonlocal commit_calls
        commit_calls += 1
        if commit_calls == 3:
            raise OSError("original third commit failure")
        real_commit(source, target)

    def keep_runtime_busy(path: Path, *args, **kwargs) -> None:
        if path.name.startswith("benchmark-v0.1.") and path.suffix == ".jsonl":
            attempted_owned_cleanup.append(path.name)
        if path.name == "benchmark-v0.1.runtime.jsonl":
            raise PermissionError("runtime file is busy")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(module, "_commit", fail_third_commit)
    monkeypatch.setattr(Path, "unlink", keep_runtime_busy)
    with pytest.raises(OSError, match="original third commit failure") as captured:
        freeze_benchmark([(case(), environment())], [review()], tmp_path)

    assert "benchmark-v0.1.runtime.jsonl" in attempted_owned_cleanup
    assert "benchmark-v0.1.labels.jsonl" in attempted_owned_cleanup
    assert (tmp_path / "benchmark-v0.1.runtime.jsonl").exists()
    assert not (tmp_path / "benchmark-v0.1.labels.jsonl").exists()
    lock = tmp_path / ".benchmark-v0.1.freeze.lock"
    assert lock.exists()
    assert any("runtime file is busy" in note for note in getattr(captured.value, "__notes__", ()))
    with pytest.raises(BlockingIOError):
        freeze_benchmark([(case(), environment())], [review()], tmp_path)


def test_existing_different_file_is_not_overwritten(tmp_path: Path) -> None:
    target = tmp_path / "benchmark-v0.1.runtime.jsonl"
    target.write_text("different\n", encoding="utf-8", newline="")
    with pytest.raises(FileExistsError, match="runtime"):
        freeze_benchmark([(case(), environment())], [review()], tmp_path)
    assert target.read_text(encoding="utf-8") == "different\n"
    assert len(list(tmp_path.iterdir())) == 1


def test_non_validated_case_is_rejected(tmp_path: Path) -> None:
    generated = case(draft_status="generated")
    with pytest.raises(ValueError, match="draft_status"):
        freeze_benchmark(
            [(generated, environment())], [review(target_case=generated)], tmp_path
        )


@pytest.mark.parametrize(
    ("case_overrides", "review_overrides"),
    [
        ({"category": "outdated", "need_research": True,
          "human_review_status": "not_required"}, {}),
        ({"human_review_status": "not_required"}, {"prior_rule_failure_count": 1}),
        ({"human_review_status": "not_required"}, {"reviewer_confidence": 0.79}),
        ({"review_status": "revise", "human_review_status": "approved"},
         {"decision": "revise", "issues": ["问题"], "suggested_changes": ["修改"]}),
        ({"review_status": "rejected", "human_review_status": "approved"},
         {"decision": "reject", "issues": ["问题"]}),
    ],
)
def test_formal_freeze_recomputes_review_gate_and_only_accepts_approved_decision(
    tmp_path: Path, case_overrides: dict, review_overrides: dict
) -> None:
    target_case = case(**case_overrides)
    target_environment = environment()
    with pytest.raises(ValueError, match="human review|approve|APPROVE"):
        freeze_benchmark(
            [(target_case, target_environment)],
            [review(
                target_case=target_case,
                target_environment=target_environment,
                **review_overrides,
            )],
            tmp_path,
        )
    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("review_status", "review_overrides"),
    [
        ("pending", {}),
        ("revise", {"decision": "revise", "issues": ["问题"],
                    "suggested_changes": ["修改"]}),
        ("rejected", {"decision": "reject", "issues": ["问题"]}),
    ],
)
def test_candidate_freeze_allows_unfinished_or_nonapproval_reviews(
    tmp_path: Path, review_status: str, review_overrides: dict
) -> None:
    target_case = case(review_status=review_status, human_review_status="pending")
    target_environment = environment()
    result = freeze_benchmark(
        [(target_case, target_environment)],
        [review(
            target_case=target_case,
            target_environment=target_environment,
            **review_overrides,
        )],
        tmp_path,
        require_human_approval=False,
    )
    expected_status = {
        "pending": "approved",
        "revise": "revise",
        "rejected": "rejected",
    }[review_status]
    audit_row = read_jsonl(result.audit_path)[0]
    assert audit_row["case"]["review_status"] == expected_status
    assert audit_row["human_review"] is None


@pytest.mark.parametrize("human_status", ["approved", "rejected"])
def test_candidate_freeze_rejects_final_human_status_and_applied_status_mismatch(
    tmp_path: Path,
    human_status: str,
) -> None:
    rejected = case(human_review_status=human_status)
    with pytest.raises(ValueError, match="human_review_status"):
        freeze_benchmark(
            [(rejected, environment())], [review(target_case=rejected)], tmp_path,
            require_human_approval=False,
        )
    mismatched = case(review_status="revise", human_review_status="pending")
    with pytest.raises(ValueError, match="disagrees"):
        freeze_benchmark(
            [(mismatched, environment())], [review(target_case=mismatched)], tmp_path,
            require_human_approval=False,
        )
