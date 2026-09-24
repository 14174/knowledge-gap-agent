import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from knowledge_gap_agent.benchmark import (
    LABEL_FIELDS,
    KnowledgeEnvironment,
    ReviewDecision,
    ReviewRecord,
    compute_environment_hash,
    freeze_benchmark,
)
from knowledge_gap_agent.contracts.benchmark import BenchmarkCase


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


def review(case_id: str = "case-b", **overrides: object) -> ReviewRecord:
    values = {
        "case_id": case_id, "decision": ReviewDecision.APPROVE, "issues": [],
        "suggested_changes": [], "evidence_refs": [f"chunk-{case_id}"],
        "reviewer_confidence": 0.9, "labeler_reasoning_seen": False,
        "prior_rule_failure_count": 0, "prompt_version": "v1", "prompt_hash": "a" * 64,
        "model_provider": "local", "model_name": "reviewer", "model_revision": "r1",
        "reviewed_at": datetime(2026, 9, 24, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return ReviewRecord(**values)


def read_jsonl(path: Path) -> list[dict]:
    raw = path.read_bytes()
    assert raw.endswith(b"\n") and b"\r\n" not in raw
    lines = raw.decode("utf-8").splitlines()
    return [json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            for line in lines]


def test_freeze_separates_runtime_labels_and_audit_and_is_stable(tmp_path: Path) -> None:
    pairs = [(case("case-b", human_review_status="approved"), environment("case-b")),
             (case("case-a", human_review_status="approved"), environment("case-a"))]
    reviews = [review("case-b", prior_rule_failure_count=1),
               review("case-a", prior_rule_failure_count=1)]
    first = freeze_benchmark(pairs, reviews, tmp_path)

    runtime = read_jsonl(first.runtime_path)
    labels = read_jsonl(first.labels_path)
    audit = read_jsonl(first.audit_path)
    assert [row["case_id"] for row in runtime] == ["case-a", "case-b"]
    assert all(LABEL_FIELDS.isdisjoint(row) for row in runtime)
    assert set(labels[0]) == {
        "case_id", "category", "need_research", "required_claim_ids",
        "missing_claim_ids", "evidence_chunk_ids", "answer_key",
    }
    assert set(audit[0]) == {"case", "review"}
    assert audit[0]["case"]["annotation_reason"] == "证据完整"
    assert audit[0]["review"]["prior_rule_failure_count"] == 1
    assert first.case_count == 2
    assert all(len(value) == 64 for value in (
        first.runtime_hash, first.labels_hash, first.audit_hash, first.dataset_hash
    ))

    second = freeze_benchmark(
        {"z": pairs[1], "a": pairs[0]}, {"z": reviews[1], "a": reviews[0]}, tmp_path
    )
    assert second == first


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_formal_freeze_rejects_unapproved_human_status_without_writes(
    tmp_path: Path, status: str
) -> None:
    with pytest.raises(ValueError, match="human_review_status"):
        freeze_benchmark([(case(human_review_status=status), environment())], [review()], tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_candidate_freeze_preserves_pending_status(tmp_path: Path) -> None:
    result = freeze_benchmark(
        [(case(human_review_status="pending"), environment())], [review()], tmp_path,
        require_human_approval=False,
    )
    assert read_jsonl(result.audit_path)[0]["case"]["human_review_status"] == "pending"


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


def test_non_validated_or_pending_review_case_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="draft_status"):
        freeze_benchmark([(case(draft_status="generated"), environment())], [review()], tmp_path)
    with pytest.raises(ValueError, match="review_status"):
        freeze_benchmark([(case(review_status="pending"), environment())], [review()], tmp_path)


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
    with pytest.raises(ValueError, match="human_review_status|approve|APPROVE"):
        freeze_benchmark(
            [(case(**case_overrides), environment())], [review(**review_overrides)], tmp_path
        )


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
    result = freeze_benchmark(
        [(case(review_status=review_status, human_review_status="pending"), environment())],
        [review(**review_overrides)], tmp_path, require_human_approval=False,
    )
    assert read_jsonl(result.audit_path)[0]["case"]["review_status"] == review_status


def test_candidate_freeze_rejects_human_rejection_and_applied_status_mismatch(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="human_review_status"):
        freeze_benchmark(
            [(case(human_review_status="rejected"), environment())], [review()], tmp_path,
            require_human_approval=False,
        )
    with pytest.raises(ValueError, match="disagrees"):
        freeze_benchmark(
            [(case(review_status="revise", human_review_status="pending"), environment())],
            [review()], tmp_path, require_human_approval=False,
        )
