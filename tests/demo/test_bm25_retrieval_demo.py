import json
from pathlib import Path
import subprocess
import sys

import pytest
import importlib


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "demo" / "02_bm25_retrieval.py"
sys.path.insert(0, str(ROOT))


def run_demo() -> tuple[bytes, dict]:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=ROOT, check=True, capture_output=True
    )
    return completed.stdout, json.loads(completed.stdout)


def test_demo_is_strict_stable_json_with_explainable_scores() -> None:
    first_bytes, payload = run_demo()
    second_bytes, second_payload = run_demo()
    assert first_bytes == second_bytes
    assert payload == second_payload
    assert set(payload) == {
        "query", "query_tokens", "top_k", "hit_claim_ids", "missing_claim_ids",
        "index_hash", "environment_hash", "result_hash",
    }
    assert payload["query_tokens"]
    assert payload["top_k"]
    for result in payload["top_k"]:
        assert set(result) == {"chunk_id", "score", "term_scores"}
        assert result["score"] == pytest.approx(sum(result["term_scores"].values()))
    assert payload["hit_claim_ids"]
    assert payload["missing_claim_ids"]
    assert all(len(payload[key]) == 64 for key in ("index_hash", "environment_hash", "result_hash"))


def test_missing_claim_exists_in_corpus_but_its_chunk_was_not_returned() -> None:
    demo = importlib.import_module("demo.02_bm25_retrieval")
    payload = demo.build_payload()
    claims_to_chunks = {
        claim_id: chunk.chunk_id
        for chunk in demo.CHUNKS
        for claim_id in chunk.claim_ids
    }
    assert set(demo.REQUIRED_CLAIM_IDS) <= set(claims_to_chunks)
    returned = {row["chunk_id"] for row in payload["top_k"]}
    assert all(claims_to_chunks[claim_id] not in returned
               for claim_id in payload["missing_claim_ids"])
