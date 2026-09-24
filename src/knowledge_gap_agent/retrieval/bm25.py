from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import isfinite, log
from numbers import Real
from typing import Any, Iterable

from knowledge_gap_agent.retrieval.tokenizer import tokenize


@dataclass(frozen=True)
class BM25SearchResult:
    chunk_id: str
    score: float
    _term_scores: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        if not isfinite(self.score):
            raise ValueError("score must be finite")
        if any(not isfinite(term_score) for _, term_score in self._term_scores):
            raise ValueError("term scores must be finite")

    @property
    def term_scores(self) -> dict[str, float]:
        return dict(self._term_scores)

    def to_payload(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "score": self.score,
            "term_scores": self.term_scores,
        }


@dataclass(frozen=True)
class _DocumentSnapshot:
    chunk_id: str
    term_frequencies: tuple[tuple[str, int], ...]
    length: int


@dataclass(frozen=True)
class BM25Index:
    _documents: tuple[_DocumentSnapshot, ...]
    _document_frequencies: tuple[tuple[str, int], ...]
    _average_document_length: float
    _k1: float
    _b: float

    @classmethod
    def build(
        cls,
        chunks: Iterable[Any],
        k1: float = 1.5,
        b: float = 0.75,
    ) -> BM25Index:
        if isinstance(k1, bool) or not isinstance(k1, Real):
            raise TypeError("k1 must be a real number")
        if not isfinite(k1):
            raise ValueError("k1 must be finite")
        if k1 <= 0:
            raise ValueError("k1 must be greater than zero")
        if isinstance(b, bool) or not isinstance(b, Real):
            raise TypeError("b must be a real number")
        if not isfinite(b):
            raise ValueError("b must be finite")
        if not 0 <= b <= 1:
            raise ValueError("b must be between zero and one")

        documents: list[_DocumentSnapshot] = []
        document_frequencies: Counter[str] = Counter()
        seen_chunk_ids: set[str] = set()
        for chunk in chunks:
            chunk_id = chunk.chunk_id
            if chunk_id in seen_chunk_ids:
                raise ValueError(f"duplicate chunk_id: {chunk_id}")
            seen_chunk_ids.add(chunk_id)

            frequencies = Counter(tokenize(chunk.text))
            documents.append(
                _DocumentSnapshot(
                    chunk_id=chunk_id,
                    term_frequencies=tuple(frequencies.items()),
                    length=sum(frequencies.values()),
                )
            )
            document_frequencies.update(frequencies.keys())

        average_length = (
            sum(document.length for document in documents) / len(documents)
            if documents
            else 0.0
        )
        return cls(
            _documents=tuple(documents),
            _document_frequencies=tuple(document_frequencies.items()),
            _average_document_length=average_length,
            _k1=k1,
            _b=b,
        )

    def search(self, query: str, top_k: int) -> list[BM25SearchResult]:
        if isinstance(top_k, bool) or not isinstance(top_k, int):
            raise TypeError("top_k must be an integer")
        if top_k < 1:
            raise ValueError("top_k must be at least one")
        query_terms = tuple(dict.fromkeys(tokenize(query)))
        if not self._documents or not query_terms:
            return []

        document_frequencies = dict(self._document_frequencies)
        document_count = len(self._documents)
        results: list[BM25SearchResult] = []
        for document in self._documents:
            frequencies = dict(document.term_frequencies)
            term_scores: dict[str, float] = {}
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if frequency == 0:
                    continue
                matching_documents = document_frequencies[term]
                inverse_document_frequency = log(
                    1
                    + (document_count - matching_documents + 0.5)
                    / (matching_documents + 0.5)
                )
                normalization = self._k1 * (
                    1
                    - self._b
                    + self._b * document.length / self._average_document_length
                )
                term_scores[term] = (
                    inverse_document_frequency
                    * frequency
                    * (self._k1 + 1)
                    / (frequency + normalization)
                )

            score = sum(term_scores.values())
            if score > 0:
                results.append(
                    BM25SearchResult(
                        chunk_id=document.chunk_id,
                        score=score,
                        _term_scores=tuple(term_scores.items()),
                    )
                )

        results.sort(key=lambda result: (-result.score, result.chunk_id))
        return results[:top_k]
