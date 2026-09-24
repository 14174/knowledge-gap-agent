import copy
import json
import pickle
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from knowledge_gap_agent.corpus.models import Claim, CorpusChunk, SourceDocument
from knowledge_gap_agent.corpus.normalize import content_hash


def make_document(**changes: object) -> SourceDocument:
    values = {
        "source_id": "source-1",
        "title": "示例来源",
        "source_url": "https://example.com/source",
        "repository": "owner/repository",
        "commit_sha": "a" * 40,
        "relative_path": "docs/source.md",
        "fetched_at": datetime(2026, 9, 24, tzinfo=UTC),
        "content_hash": content_hash("正文"),
        "content": "正文",
    }
    values.update(changes)
    return SourceDocument(**values)


def make_chunk(**changes: object) -> CorpusChunk:
    values = {
        "chunk_id": "chunk-1",
        "source_id": "source-1",
        "heading_path": ["一级", "二级"],
        "start_line": 1,
        "end_line": 2,
        "text": "证据正文",
        "token_terms": ["证据", "正文"],
        "content_hash": content_hash("证据正文"),
        "claim_ids": ["claim-1"],
    }
    values.update(changes)
    return CorpusChunk(**values)


def make_claim(**changes: object) -> Claim:
    values = {
        "claim_id": "claim-1",
        "statement": "需要检索缺失证据。",
        "evidence_chunk_ids": ["chunk-1"],
        "valid_from": datetime(2026, 1, 1, tzinfo=UTC),
        "valid_until": datetime(2026, 12, 31, tzinfo=UTC),
        "conflicts_with": ["claim-2"],
    }
    values.update(changes)
    return Claim(**values)


def test_source_document_rejects_wrong_content_hash() -> None:
    with pytest.raises(ValidationError, match="content_hash"):
        make_document(content_hash="0" * 64)


@pytest.mark.parametrize("commit_sha", ["a" * 39, "A" * 40, "g" * 40])
def test_source_document_rejects_invalid_commit_sha(commit_sha: str) -> None:
    with pytest.raises(ValidationError, match="commit_sha"):
        make_document(commit_sha=commit_sha)


def test_chunk_rejects_reversed_line_range() -> None:
    with pytest.raises(ValidationError, match="end_line"):
        make_chunk(start_line=3, end_line=2)


def test_chunk_rejects_wrong_content_hash() -> None:
    with pytest.raises(ValidationError, match="content_hash"):
        make_chunk(content_hash="0" * 64)


def test_claim_rejects_self_conflict() -> None:
    with pytest.raises(ValidationError, match="conflicts_with"):
        make_claim(conflicts_with=["claim-1"])


def test_claim_rejects_reversed_validity_period() -> None:
    with pytest.raises(ValidationError, match="valid_until"):
        make_claim(
            valid_from=datetime(2026, 2, 1, tzinfo=UTC),
            valid_until=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_source_document_rejects_naive_fetched_at() -> None:
    with pytest.raises(ValidationError, match="fetched_at"):
        make_document(fetched_at=datetime(2026, 9, 25))


@pytest.mark.parametrize("field", ["valid_from", "valid_until"])
def test_claim_rejects_naive_validity_time(field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        make_claim(**{field: datetime(2026, 9, 25)})


@pytest.mark.parametrize(
    "changes",
    [
        {"fetched_at": datetime(2026, 9, 25)},
        {"content_hash": "0" * 64},
    ],
)
def test_source_document_dump_then_validate_rejects_model_copy_bypasses(
    changes: dict[str, object],
) -> None:
    bypassed = make_document().model_copy(update=changes)

    # 不直接 model_validate(instance)：它不是项目跨信任边界的重验方式。
    with pytest.raises(ValidationError):
        SourceDocument.model_validate(bypassed.model_dump(mode="python"))


@pytest.mark.parametrize("field", ["valid_from", "valid_until"])
def test_claim_dump_then_validate_rejects_naive_model_copy_time(field: str) -> None:
    bypassed = make_claim().model_copy(update={field: datetime(2026, 9, 25)})

    # 不直接 model_validate(instance)；先转储再重验不得冒日期比较的裸 TypeError。
    with pytest.raises(ValidationError, match=field):
        Claim.model_validate(bypassed.model_dump(mode="python"))


@pytest.mark.parametrize(
    ("factory", "field"),
    [(make_document, "source_id"), (make_chunk, "text"), (make_claim, "statement")],
)
def test_models_reject_blank_required_strings(factory, field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        factory(**{field: "   "})


def test_models_reject_noncanonical_hash_format() -> None:
    with pytest.raises(ValidationError, match="content_hash"):
        make_chunk(content_hash="A" * 64)


def test_valid_models_are_frozen_forbid_extras_and_serialize() -> None:
    document = make_document()
    chunk = make_chunk()
    claim = make_claim()

    assert document.model_dump(mode="json")["fetched_at"] == "2026-09-24T00:00:00Z"
    assert chunk.model_dump(mode="json")["heading_path"] == ["一级", "二级"]
    assert claim.model_dump(mode="json")["valid_until"] == "2026-12-31T00:00:00Z"
    with pytest.raises(ValidationError, match="frozen"):
        document.title = "新标题"
    with pytest.raises(ValidationError, match="extra"):
        make_claim(extra="forbidden")


COLLECTION_FIELDS = [
    (make_chunk, "heading_path"),
    (make_chunk, "token_terms"),
    (make_chunk, "claim_ids"),
    (make_claim, "evidence_chunk_ids"),
    (make_claim, "conflicts_with"),
]


@pytest.mark.parametrize(("factory", "field"), COLLECTION_FIELDS)
def test_collection_fields_are_immutable_tuples(factory, field: str) -> None:
    model = factory()
    values = getattr(model, field)

    assert isinstance(values, tuple)
    with pytest.raises(AttributeError):
        values.append("changed")
    with pytest.raises(TypeError):
        values[0] = "changed"


@pytest.mark.parametrize(("factory", "field"), COLLECTION_FIELDS)
def test_tuple_fields_support_copy_and_serialization_roundtrips(factory, field: str) -> None:
    model = factory()
    expected = getattr(model, field)

    assert getattr(copy.copy(model), field) == expected
    assert getattr(copy.deepcopy(model), field) == expected
    assert getattr(model.model_copy(deep=True), field) == expected
    assert getattr(pickle.loads(pickle.dumps(model)), field) == expected

    json_payload = model.model_dump(mode="json")
    assert isinstance(json_payload[field], list)
    assert isinstance(json.loads(model.model_dump_json())[field], list)
