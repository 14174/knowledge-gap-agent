import json
from math import log
from types import SimpleNamespace

import pytest

from knowledge_gap_agent.retrieval.bm25 import BM25Index


def chunk(chunk_id: str, text: str, token_terms: tuple[str, ...] = ()) -> SimpleNamespace:
    return SimpleNamespace(chunk_id=chunk_id, text=text, token_terms=token_terms)


def test_bm25_matches_independently_hand_calculated_scores() -> None:
    index = BM25Index.build(
        [chunk("a", "apple apple banana"), chunk("b", "apple carrot carrot")]
    )

    results = index.search("apple banana", top_k=2)

    # 两篇文档均长 3，故长度归一化项为 1。以下数值由公式独立手算。
    assert [result.chunk_id for result in results] == ["a", "b"]
    assert results[0].term_scores["apple"] == pytest.approx(0.26045936684850657)
    assert results[0].term_scores["banana"] == pytest.approx(0.6931471805599453)
    assert results[0].score == pytest.approx(0.9536065474084518)
    assert results[1].score == pytest.approx(0.1823215567939546)
    assert results[0].score == pytest.approx(sum(results[0].term_scores.values()))


def test_bm25_normalizes_for_document_length() -> None:
    index = BM25Index.build([chunk("short", "apple"), chunk("long", "apple x y")])

    results = {result.chunk_id: result.score for result in index.search("apple", top_k=2)}

    assert results["short"] == pytest.approx(0.23525362166961883)
    assert results["long"] == pytest.approx(0.1488339722067026)


def test_bm25_breaks_equal_scores_by_chunk_id() -> None:
    index = BM25Index.build([chunk("b", "相同"), chunk("a", "相同")])

    assert [result.chunk_id for result in index.search("相同", top_k=2)] == ["a", "b"]


def test_bm25_ignores_prefilled_token_terms() -> None:
    index = BM25Index.build([chunk("a", "actual", token_terms=("wrong",))])

    assert [result.chunk_id for result in index.search("actual", top_k=1)] == ["a"]
    assert index.search("wrong", top_k=1) == []


def test_query_terms_are_unique_in_first_seen_order() -> None:
    index = BM25Index.build([chunk("a", "apple banana")])

    result = index.search("banana apple banana", top_k=1)[0]

    assert list(result.term_scores) == ["banana", "apple"]
    assert result.score == pytest.approx(2 * log(4 / 3))


def test_result_payload_is_fully_json_serializable() -> None:
    result = BM25Index.build([chunk("a", "apple")]).search("apple", top_k=1)[0]

    payload = result.to_payload()

    assert json.loads(json.dumps(payload, allow_nan=False)) == {
        "chunk_id": "a",
        "score": pytest.approx(log(4 / 3)),
        "term_scores": {"apple": pytest.approx(log(4 / 3))},
    }


def test_term_scores_returns_a_defensive_copy() -> None:
    result = BM25Index.build([chunk("a", "apple")]).search("apple", top_k=1)[0]

    exposed_scores = result.term_scores
    exposed_scores["apple"] = 0.0
    exposed_scores["injected"] = 1.0

    assert result.term_scores == {"apple": pytest.approx(log(4 / 3))}
    assert result.score == pytest.approx(log(4 / 3))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [({"k1": 0}, "k1"), ({"k1": -0.1}, "k1"), ({"b": -0.1}, "b"), ({"b": 1.1}, "b")],
)
def test_build_rejects_invalid_parameters(kwargs: dict[str, float], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        BM25Index.build([], **kwargs)


def test_build_accepts_parameter_boundaries() -> None:
    BM25Index.build([], k1=0.1, b=0)
    BM25Index.build([], k1=0.1, b=1)


@pytest.mark.parametrize("field", ["k1", "b"])
@pytest.mark.parametrize("value", [True, False, "1", None])
def test_build_rejects_non_real_or_boolean_parameters(field: str, value: object) -> None:
    with pytest.raises(TypeError, match=field):
        BM25Index.build([], **{field: value})


@pytest.mark.parametrize("field", ["k1", "b"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_build_rejects_non_finite_parameters(field: str, value: float) -> None:
    with pytest.raises(ValueError, match=field):
        BM25Index.build([], **{field: value})


def test_build_rejects_duplicate_chunk_ids() -> None:
    with pytest.raises(ValueError, match="duplicate|重复"):
        BM25Index.build([chunk("same", "one"), chunk("same", "two")])


def test_index_uses_a_frozen_snapshot() -> None:
    original_chunk = chunk("a", "apple")
    source_chunks = [original_chunk]
    index = BM25Index.build(source_chunks)

    original_chunk.text = "changed"
    source_chunks.clear()
    source_chunks.append(chunk("b", "apple"))

    assert [result.chunk_id for result in index.search("apple", top_k=2)] == ["a"]
    assert index.search("changed", top_k=2) == []


def test_empty_corpus_empty_query_and_oov_return_no_results() -> None:
    assert BM25Index.build([]).search("apple", top_k=1) == []
    index = BM25Index.build([chunk("a", "apple")])
    assert index.search("", top_k=1) == []
    assert index.search("unknown", top_k=1) == []


@pytest.mark.parametrize("top_k", [0, -1])
def test_search_rejects_non_positive_top_k(top_k: int) -> None:
    with pytest.raises(ValueError, match="top_k"):
        BM25Index.build([]).search("apple", top_k=top_k)


@pytest.mark.parametrize(
    "top_k", [True, False, 1.0, float("nan"), float("inf"), "1", None]
)
def test_search_rejects_non_integer_or_boolean_top_k(top_k: object) -> None:
    with pytest.raises(TypeError, match="top_k"):
        BM25Index.build([]).search("apple", top_k=top_k)
