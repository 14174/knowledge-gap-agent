from dataclasses import dataclass
import hashlib
from pathlib import Path

from knowledge_gap_agent.benchmark.models import KnowledgeEnvironment
from knowledge_gap_agent.benchmark.review import ReviewRecord, compute_review_target_hash
from knowledge_gap_agent.benchmark.validation import validate_dataset
from knowledge_gap_agent.contracts.benchmark import BenchmarkCase
from knowledge_gap_agent.corpus.models import Claim, CorpusChunk
from knowledge_gap_agent.retrieval.bm25 import BM25Index
from knowledge_gap_agent.runtime.models import EvidenceView, TaskInput
from knowledge_gap_agent.utils.canonical import sha256_hex
from .io import read_json, read_jsonl, write_jsonl_once, write_once, file_hash, verify_file


@dataclass(frozen=True)
class DatasetCase:
    case: BenchmarkCase
    environment: KnowledgeEnvironment

    @property
    def case_id(self):
        return self.case.case_id

    @property
    def topic(self):
        return int(self.case.base_question_id.split("-")[-1])


class ResearchTool:
    def __init__(self, chunks, visible):
        self.chunks = {chunk.chunk_id: chunk for chunk in chunks}
        self.index = BM25Index.build(self.chunks.values())
        self.ref_map = {}
        self._chunk_refs = {}
        self.queries = []
        self.visible_ids = frozenset(visible)

    def view(self, chunk_id):
        chunk = self.chunks[chunk_id]
        if chunk_id not in self._chunk_refs:
            ref = f"E{len(self.ref_map) + 1}"
            self._chunk_refs[chunk_id] = ref
            self.ref_map[ref] = chunk_id
        return EvidenceView(ref_id=self._chunk_refs[chunk_id], text=chunk.text,
                            source_id=chunk.source_id,
                            content_hash=hashlib.sha256(chunk.text.encode("utf-8")).hexdigest())

    def __call__(self, query):
        self.queries.append(query)
        return tuple(self.view(hit.chunk_id) for hit in self.index.search(query, top_k=4))


@dataclass(frozen=True)
class CandidateDataset:
    cases: tuple[DatasetCase, ...]
    chunks: tuple[CorpusChunk, ...]
    source_hashes: dict
    dataset_hash: str

    @property
    def evaluation_cases(self):
        return tuple(case for case in self.cases if case.topic >= 5)

    @property
    def development_cases(self):
        return tuple(case for case in self.cases if case.topic <= 4)

    def by_id(self, case_id):
        return next(case for case in self.cases if case.case_id == case_id)

    def prepare(self, case_id, *, question=None, include_local=True):
        case = self.by_id(case_id)
        env = case.environment
        allowed = set(env.visible_chunk_ids + env.research_chunk_ids)
        tool = ResearchTool([chunk for chunk in self.chunks if chunk.chunk_id in allowed], env.visible_chunk_ids)
        query = question or case.case.question
        if include_local:
            visible = [chunk for chunk in self.chunks if chunk.chunk_id in set(env.visible_chunk_ids)]
            ids = [hit.chunk_id for hit in BM25Index.build(visible).search(query, top_k=4)]
            knowledge = tuple(tool.view(chunk_id) for chunk_id in ids)
        else:
            knowledge = ()
        return TaskInput(question=query, knowledge=knowledge), tool


def load_candidate_dataset(root):
    root = Path(root)
    relative = ["fixtures/benchmark/drafts.jsonl", "fixtures/benchmark/reviews.jsonl",
                "fixtures/corpus/chunks.jsonl", "fixtures/corpus/claims.jsonl"]
    relative += ["fixtures/corpus/documents.jsonl", "fixtures/sources/manifest.json"]
    hashes = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in relative}
    cases = tuple(DatasetCase(BenchmarkCase.model_validate(row["case"]),
                             KnowledgeEnvironment.model_validate(row["environment"]))
                  for row in read_jsonl(root / relative[0], verify=False))
    reviews = [ReviewRecord.model_validate(row) for row in read_jsonl(root / relative[1], verify=False)]
    chunks = tuple(CorpusChunk.model_validate(row) for row in read_jsonl(root / relative[2], verify=False))
    claims = tuple(Claim.model_validate(row) for row in read_jsonl(root / relative[3], verify=False))
    issues = validate_dataset([item.case for item in cases], [item.environment for item in cases], chunks, claims)
    if issues:
        raise ValueError(f"候选结构校验失败：{issues[0].code}")
    by_id = {review.case_id: review for review in reviews}
    if len(by_id) != len(reviews) or set(by_id) != {item.case_id for item in cases}:
        raise ValueError("候选与独立复核集合不一致")
    for item in cases:
        review = by_id[item.case_id]
        if review.review_target_hash != compute_review_target_hash(item.case, item.environment, chunks, claims):
            raise ValueError("复核目标已经变化")
        if review.decision.value != "approve":
            raise ValueError("存在未批准模型复核")
    return CandidateDataset(cases, chunks, hashes, sha256_hex(hashes))


def snapshot_dataset(dataset, directory):
    directory = Path(directory)
    runtime, labels, audit = [], [], []
    for item in dataset.cases:
        task, tool = dataset.prepare(item.case_id)
        runtime.append({"case_id": item.case_id, "task": task.model_dump(mode="json")})
        labels.append({"case_id": item.case_id, "topic": item.topic,
                       "answer_key": list(item.case.answer_key), "need_research": item.case.need_research,
                       "category": item.case.category.value})
        audit.append({"case": item.case.model_dump(mode="json"),
                      "environment": item.environment.model_dump(mode="json"), "initial_ref_map": tool.ref_map})
    write_jsonl_once(directory / "runtime/tasks.jsonl", runtime)
    write_jsonl_once(directory / "labels/cases.jsonl", labels)
    write_jsonl_once(directory / "audit/cases.jsonl", audit)
    write_once(directory / "audit/metadata.json", {"status": "candidate_not_human_approved",
               "pending_human_review": sum(item.case.human_review_status.value == "pending" for item in dataset.cases),
               "source_hashes": dataset.source_hashes, "dataset_hash": dataset.dataset_hash})
    names = ("runtime/tasks.jsonl", "labels/cases.jsonl", "audit/cases.jsonl", "audit/metadata.json")
    write_once(directory / "manifest.json", {"files": {name: file_hash(directory / name) for name in names}})


def verify_snapshot(directory):
    directory = Path(directory)
    manifest = read_json(directory / "manifest.json")
    expected = {"runtime/tasks.jsonl", "labels/cases.jsonl", "audit/cases.jsonl", "audit/metadata.json"}
    if set(manifest["files"]) != expected:
        raise ValueError("快照摘要清单不完整")
    for name, digest in manifest["files"].items():
        verify_file(directory / name)
        if file_hash(directory / name) != digest:
            raise ValueError("快照文件摘要失配")
