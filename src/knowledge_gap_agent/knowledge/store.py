import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

from knowledge_gap_agent.knowledge.verification import VerifiedCandidate, digest, revalidate
from knowledge_gap_agent.retrieval.bm25 import BM25Index
from knowledge_gap_agent.runtime.models import EvidenceView, FrozenModel


class KnowledgeEntry(FrozenModel):
    knowledge_id: str
    text: str
    evidence_refs: tuple[str, ...]
    source_ids: tuple[str, ...]
    content_hash: str
    source_run: str
    written_at: datetime

    @property
    def chunk_id(self) -> str:
        return self.knowledge_id

    def as_evidence(self) -> EvidenceView:
        return EvidenceView(ref_id=self.knowledge_id, text=self.text,
                            source_id=self.source_ids[0], source_ids=self.source_ids,
                            content_hash=self.content_hash)


class KnowledgeHit(KnowledgeEntry):
    score: float


class SQLiteKnowledgeProvider:
    def __init__(self, path: str | Path):
        self._connection = sqlite3.connect(path)
        self._connection.execute("CREATE TABLE IF NOT EXISTS knowledge (id TEXT PRIMARY KEY, payload TEXT NOT NULL, verification TEXT NOT NULL)")
        self._connection.commit()

    def put_verified(self, candidate: VerifiedCandidate) -> KnowledgeEntry:
        candidate = revalidate(candidate)
        by_ref = {e.ref_id: e for e in candidate.evidence}
        source_evidence = sorted({(source, by_ref[r].content_hash)
            for r in candidate.evidence_refs
            for source in (by_ref[r].source_ids or (by_ref[r].source_id,))})
        sources = tuple(sorted({source for source, _ in source_evidence}))
        # 身份不依赖临时引用和单次运行；正文与实际出处决定稳定编号。
        knowledge_id = "knowledge-" + digest({"text": candidate.text,
            "source_evidence": source_evidence})
        entry = KnowledgeEntry(knowledge_id=knowledge_id, text=candidate.text,
            evidence_refs=candidate.evidence_refs, source_ids=sources,
            content_hash=hashlib.sha256(candidate.text.encode()).hexdigest(),
            source_run=candidate.source_run, written_at=candidate.verified_at)
        with self._connection:
            self._connection.execute("INSERT OR IGNORE INTO knowledge VALUES (?, ?, ?)",
                (knowledge_id, entry.model_dump_json(), candidate.model_dump_json()))
        row = self._connection.execute("SELECT payload FROM knowledge WHERE id=?", (knowledge_id,)).fetchone()
        return KnowledgeEntry.model_validate_json(row[0])

    def entries(self) -> tuple[KnowledgeEntry, ...]:
        return tuple(KnowledgeEntry.model_validate_json(row[0]) for row in
                     self._connection.execute("SELECT payload FROM knowledge ORDER BY id"))

    def search(self, query: str, top_k: int = 4) -> tuple[KnowledgeHit, ...]:
        entries = self.entries()
        by_id = {e.knowledge_id: e for e in entries}
        hits = BM25Index.build(entries).search(query, top_k)
        return tuple(KnowledgeHit(**by_id[h.chunk_id].model_dump(), score=h.score) for h in hits)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
