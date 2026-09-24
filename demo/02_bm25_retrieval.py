"""使用固定本地语料演示可解释、可复现的 BM25 检索。"""

from dataclasses import dataclass
import sys

from knowledge_gap_agent.benchmark import compute_environment_hash
from knowledge_gap_agent.retrieval.bm25 import BM25Index
from knowledge_gap_agent.retrieval.tokenizer import tokenize
from knowledge_gap_agent.utils.canonical import canonical_json, sha256_hex


@dataclass(frozen=True)
class DemoChunk:
    chunk_id: str
    text: str
    claim_ids: tuple[str, ...]


QUERY = "BM25 如何解释检索分数"
REQUIRED_CLAIM_IDS = ("claim-formula", "claim-human-review")
CHUNKS = (
    DemoChunk("chunk-formula", "BM25 检索分数由每个查询词项的贡献相加得到。", ("claim-formula",)),
    DemoChunk("chunk-gate", "冻结基准需要校验复核状态与证据引用。", ("claim-freeze",)),
    DemoChunk("chunk-human-review", "人工终审负责处理高风险基准样本。", ("claim-human-review",)),
    DemoChunk("chunk-token", "中文检索使用确定性的二元字组分词。", ("claim-tokenizer",)),
)


def build_payload() -> dict[str, object]:
    index = BM25Index.build(CHUNKS)
    results = index.search(QUERY, top_k=2)
    result_rows = [result.to_payload() for result in results]
    returned_ids = {result.chunk_id for result in results}
    hit_claim_ids = sorted({
        claim_id for chunk in CHUNKS if chunk.chunk_id in returned_ids
        for claim_id in chunk.claim_ids if claim_id in REQUIRED_CLAIM_IDS
    })
    missing_claim_ids = sorted(set(REQUIRED_CLAIM_IDS) - set(hit_claim_ids))
    index_hash = sha256_hex({
        "k1": 1.5, "b": 0.75,
        "chunks": [
            {"chunk_id": chunk.chunk_id, "text": chunk.text, "claim_ids": list(chunk.claim_ids)}
            for chunk in sorted(CHUNKS, key=lambda item: item.chunk_id)
        ],
    })
    environment_hash = compute_environment_hash(
        "demo-local", [chunk.chunk_id for chunk in CHUNKS], [], []
    )
    payload: dict[str, object] = {
        "query": QUERY,
        "query_tokens": tokenize(QUERY),
        "top_k": result_rows,
        "hit_claim_ids": hit_claim_ids,
        "missing_claim_ids": missing_claim_ids,
        "index_hash": index_hash,
        "environment_hash": environment_hash,
    }
    payload["result_hash"] = sha256_hex(payload)
    return payload


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    print(canonical_json(build_payload()))


if __name__ == "__main__":
    main()
