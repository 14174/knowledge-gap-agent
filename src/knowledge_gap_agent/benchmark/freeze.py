from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile

from knowledge_gap_agent.benchmark.models import (
    HumanReviewDecision,
    HumanReviewRecord,
    KnowledgeEnvironment,
)
from knowledge_gap_agent.benchmark.review import (
    ReviewDecision,
    ReviewRecord,
    compute_review_target_hash,
    requires_human_review,
)
from knowledge_gap_agent.benchmark.validation import build_runtime_payload
from knowledge_gap_agent.contracts.benchmark import (
    BenchmarkCase,
    DraftStatus,
    HumanReviewStatus,
    ReviewStatus,
)
from knowledge_gap_agent.corpus.models import Claim, CorpusChunk
from knowledge_gap_agent.utils.canonical import canonical_json, sha256_hex


DATASET_VERSION = "v0.1"


@dataclass(frozen=True)
class FreezeResult:
    runtime_path: Path
    labels_path: Path
    audit_path: Path
    runtime_content_hash: str
    labels_content_hash: str
    audit_content_hash: str
    dataset_hash: str
    case_count: int

    @property
    def runtime_hash(self) -> str:
        return self.runtime_content_hash

    @property
    def labels_hash(self) -> str:
        return self.labels_content_hash

    @property
    def audit_hash(self) -> str:
        return self.audit_content_hash


def _values(value: object) -> tuple:
    if isinstance(value, Mapping):
        return tuple(value.values())
    return tuple(value)  # type: ignore[arg-type]


def _revalidate_pairs(cases: object) -> tuple[tuple[BenchmarkCase, KnowledgeEnvironment], ...]:
    pairs: list[tuple[BenchmarkCase, KnowledgeEnvironment]] = []
    for item in _values(cases):
        try:
            raw_case, raw_environment = item
        except (TypeError, ValueError) as exc:
            raise TypeError("cases must contain (BenchmarkCase, KnowledgeEnvironment) pairs") from exc
        validated_case = BenchmarkCase.model_validate(raw_case.model_dump(mode="python"))
        validated_environment = KnowledgeEnvironment.model_validate(
            raw_environment.model_dump(mode="python")
        )
        if validated_case.environment_id != validated_environment.environment_id:
            raise ValueError(
                f"case_id={validated_case.case_id}: environment_id does not match environment"
            )
        pairs.append((validated_case, validated_environment))
    return tuple(pairs)


def _index_reviews(reviews: object) -> dict[str, ReviewRecord]:
    result: dict[str, ReviewRecord] = {}
    for raw_review in _values(reviews):
        review = ReviewRecord.model_validate(raw_review.model_dump(mode="python"))
        if review.case_id in result:
            raise ValueError(f"duplicate review case_id: {review.case_id}")
        result[review.case_id] = review
    return result


def _index_human_reviews(human_reviews: object) -> dict[str, HumanReviewRecord]:
    result: dict[str, HumanReviewRecord] = {}
    for raw_review in _values(human_reviews):
        review = HumanReviewRecord.model_validate(
            raw_review.model_dump(mode="python")
        )
        if review.case_id in result:
            raise ValueError(f"duplicate human review case_id: {review.case_id}")
        result[review.case_id] = review
    return result


def _jsonl(rows: Iterable[dict]) -> bytes:
    return ("".join(f"{canonical_json(row)}\n" for row in rows)).encode("utf-8")


def _content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _commit(source: Path, target: Path) -> None:
    """在同一文件系统中只创建目标，绝不覆盖并发产生的文件。"""
    os.link(source, target)


def _identity(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino


def _safe_unlink_owned(path: Path, identity: tuple[int, int], expected_hash: str) -> None:
    try:
        if _identity(path) == identity and _content_hash(path.read_bytes()) == expected_hash:
            path.unlink()
    except FileNotFoundError:
        return


def _write_files_atomically(contents: Mapping[Path, bytes]) -> None:
    for target, content in contents.items():
        if target.exists() and target.read_bytes() != content:
            raise FileExistsError(f"refusing to overwrite different file: {target.name}")

    pending = {path: content for path, content in contents.items() if not path.exists()}
    if not pending:
        return
    parent = next(iter(pending)).parent
    temporary_paths: dict[Path, Path] = {}
    possible_targets: list[tuple[Path, tuple[int, int], str]] = []
    try:
        for target, content in pending.items():
            descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=parent)
            temporary = Path(name)
            temporary_paths[target] = temporary
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        for target, temporary in temporary_paths.items():
            expected_hash = _content_hash(pending[target])
            source_identity = _identity(temporary)
            possible_targets.append((target, source_identity, expected_hash))
            _commit(temporary, target)
            if _identity(target) != source_identity:
                raise OSError(f"committed target identity changed: {target.name}")
        for temporary in temporary_paths.values():
            temporary.unlink(missing_ok=True)
    except BaseException as primary_error:
        cleanup_errors: list[BaseException] = []
        for target, identity, expected_hash in possible_targets:
            try:
                _safe_unlink_owned(target, identity, expected_hash)
            except (OSError, RuntimeError) as cleanup_error:
                cleanup_errors.append(cleanup_error)
        for temporary in temporary_paths.values():
            try:
                temporary.unlink(missing_ok=True)
            except (OSError, RuntimeError) as cleanup_error:
                cleanup_errors.append(cleanup_error)
        if cleanup_errors:
            setattr(primary_error, "_freeze_cleanup_failed", True)
            for cleanup_error in cleanup_errors:
                primary_error.add_note(
                    f"freeze cleanup failed: {type(cleanup_error).__name__}: {cleanup_error}"
                )
        raise


def _write_with_lock(directory: Path, contents: Mapping[Path, bytes]) -> None:
    lock_path = directory / f".benchmark-{DATASET_VERSION}.freeze.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise BlockingIOError(f"benchmark freeze is locked: {lock_path.name}") from exc
    lock_stat = os.fstat(descriptor)
    lock_identity = (lock_stat.st_dev, lock_stat.st_ino)
    try:
        _write_files_atomically(contents)
    except BaseException as primary_error:
        os.close(descriptor)
        if getattr(primary_error, "_freeze_cleanup_failed", False):
            raise
        try:
            if _identity(lock_path) == lock_identity:
                lock_path.unlink()
        except (OSError, RuntimeError) as cleanup_error:
            primary_error.add_note(
                f"freeze lock cleanup failed: {type(cleanup_error).__name__}: {cleanup_error}"
            )
        raise
    os.close(descriptor)
    try:
        if _identity(lock_path) == lock_identity:
            lock_path.unlink()
    except FileNotFoundError:
        pass


def freeze_benchmark(
    cases: object,
    reviews: object,
    chunks: Iterable[CorpusChunk],
    claims: Iterable[Claim],
    output_dir: str | Path,
    require_human_approval: bool = True,
    *,
    human_reviews: object = (),
) -> FreezeResult:
    pairs = _revalidate_pairs(cases)
    reviews_by_id = _index_reviews(reviews)
    human_reviews_by_id = _index_human_reviews(human_reviews)
    if not require_human_approval and human_reviews_by_id:
        raise ValueError("candidate freeze does not accept human review records")
    corpus_chunks = tuple(chunks)
    corpus_claims = tuple(claims)
    cases_by_id: dict[str, tuple[BenchmarkCase, KnowledgeEnvironment]] = {}
    for pair in pairs:
        case = pair[0]
        if case.case_id in cases_by_id:
            raise ValueError(f"duplicate case_id: {case.case_id}")
        cases_by_id[case.case_id] = pair

    case_ids = set(cases_by_id)
    review_ids = set(reviews_by_id)
    if case_ids != review_ids:
        raise ValueError(
            f"case/review mismatch: missing reviews={sorted(case_ids - review_ids)!r}; "
            f"extra reviews={sorted(review_ids - case_ids)!r}"
        )

    expected_status = {
        ReviewDecision.APPROVE: ReviewStatus.APPROVED,
        ReviewDecision.REVISE: ReviewStatus.REVISE,
        ReviewDecision.REJECT: ReviewStatus.REJECTED,
    }
    required_human_case_ids: set[str] = set()
    target_hashes: dict[str, str] = {}
    for case_id in sorted(case_ids):
        case, environment = cases_by_id[case_id]
        review = reviews_by_id[case_id]
        target_hash = compute_review_target_hash(
            case, environment, corpus_chunks, corpus_claims
        )
        target_hashes[case_id] = target_hash
        if review.review_target_hash != target_hash:
            raise ValueError(
                f"case_id={case_id}: review_target_hash does not match current draft"
            )
        if case.draft_status is not DraftStatus.VALIDATED:
            raise ValueError(f"case_id={case_id}: draft_status must be validated")
        environment_chunk_ids = set(environment.visible_chunk_ids)
        environment_chunk_ids.update(environment.research_chunk_ids)
        environment_chunk_ids.update(environment.excluded_chunk_ids)
        unknown_refs = sorted(set(review.evidence_refs) - environment_chunk_ids)
        if unknown_refs:
            raise ValueError(
                f"case_id={case_id}: evidence_refs contain unknown refs: {unknown_refs!r}"
            )
        if (
            case.review_status is not ReviewStatus.PENDING
            and case.review_status is not expected_status[review.decision]
        ):
            raise ValueError(f"case_id={case_id}: review_status disagrees with review decision")
        if not require_human_approval:
            if case.human_review_status in {
                HumanReviewStatus.APPROVED,
                HumanReviewStatus.REJECTED,
            }:
                raise ValueError(
                    f"case_id={case_id}: human_review_status="
                    f"{case.human_review_status.value} is final and is not eligible "
                    "for candidate freeze"
                )
            continue

        if review.decision is not ReviewDecision.APPROVE:
            raise ValueError(
                f"case_id={case_id}: formal freeze requires review decision approve"
            )
        if requires_human_review(case, review):
            required_human_case_ids.add(case_id)

    if require_human_approval:
        human_case_ids = set(human_reviews_by_id)
        missing = sorted(required_human_case_ids - human_case_ids)
        extra = sorted(human_case_ids - required_human_case_ids)
        if missing or extra:
            raise ValueError(
                f"human review case set mismatch: missing human reviews={missing!r}; "
                f"extra human reviews={extra!r}"
            )

        for case_id in sorted(required_human_case_ids):
            record = human_reviews_by_id[case_id]
            if record.review_target_hash != target_hashes[case_id]:
                raise ValueError(
                    f"case_id={case_id}: human review_target_hash does not match "
                    "current draft"
                )
            if record.decision is not HumanReviewDecision.APPROVED:
                raise ValueError(
                    f"case_id={case_id}: human review decision="
                    f"{record.decision.value} is not eligible for formal freeze"
                )

    frozen_cases_by_id: dict[str, BenchmarkCase] = {}
    for case_id in sorted(case_ids):
        case, _ = cases_by_id[case_id]
        review = reviews_by_id[case_id]
        review_status = expected_status[review.decision]
        if require_human_approval:
            human_status = (
                HumanReviewStatus.APPROVED
                if case_id in required_human_case_ids
                else HumanReviewStatus.NOT_REQUIRED
            )
            if (
                case.human_review_status
                in {HumanReviewStatus.APPROVED, HumanReviewStatus.REJECTED}
                and case.human_review_status is not human_status
            ):
                raise ValueError(
                    f"case_id={case_id}: human_review_status disagrees with "
                    "trusted human review record"
                )
        else:
            human_status = (
                HumanReviewStatus.PENDING
                if requires_human_review(case, review)
                else HumanReviewStatus.NOT_REQUIRED
            )
        frozen_cases_by_id[case_id] = case.model_copy(update={
            "review_status": review_status,
            "human_review_status": human_status,
        })

    runtime_rows = []
    label_rows = []
    audit_rows = []
    for case_id in sorted(case_ids):
        _, environment = cases_by_id[case_id]
        case = frozen_cases_by_id[case_id]
        review = reviews_by_id[case_id]
        runtime_rows.append(build_runtime_payload(case, environment))
        label_rows.append({
            "case_id": case.case_id,
            "category": case.category.value,
            "need_research": case.need_research,
            "required_claim_ids": list(case.required_claim_ids),
            "missing_claim_ids": list(case.missing_claim_ids),
            "evidence_chunk_ids": list(case.evidence_chunk_ids),
            "answer_key": list(case.answer_key),
        })
        audit_rows.append({
            "case": case.model_dump(mode="json"),
            "review": review.model_dump(mode="json"),
            "human_review": (
                human_reviews_by_id[case_id].model_dump(mode="json")
                if case_id in required_human_case_ids
                else None
            ),
        })

    runtime_content = _jsonl(runtime_rows)
    labels_content = _jsonl(label_rows)
    audit_content = _jsonl(audit_rows)
    runtime_hash = _content_hash(runtime_content)
    labels_hash = _content_hash(labels_content)
    audit_hash = _content_hash(audit_content)
    dataset_hash = sha256_hex({
        "version": DATASET_VERSION,
        "runtime_hash": runtime_hash,
        "labels_hash": labels_hash,
        "audit_hash": audit_hash,
    })

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    runtime_path = directory / f"benchmark-{DATASET_VERSION}.runtime.jsonl"
    labels_path = directory / f"benchmark-{DATASET_VERSION}.labels.jsonl"
    audit_path = directory / f"benchmark-{DATASET_VERSION}.audit.jsonl"
    _write_with_lock(directory, {
        runtime_path: runtime_content,
        labels_path: labels_content,
        audit_path: audit_content,
    })
    return FreezeResult(
        runtime_path=runtime_path, labels_path=labels_path, audit_path=audit_path,
        runtime_content_hash=runtime_hash, labels_content_hash=labels_hash,
        audit_content_hash=audit_hash,
        dataset_hash=dataset_hash, case_count=len(case_ids),
    )
