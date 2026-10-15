"""固定响应工程演示：知识持久化与确定性检索，不代表效果实验。"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from knowledge_gap_agent.knowledge.store import SQLiteKnowledgeProvider
from knowledge_gap_agent.knowledge.verification import verify_candidate
from knowledge_gap_agent.runtime.models import EvidenceView, ModelReply


class FixedReview:
    def complete(self, system, payload, *, max_tokens=1800):
        return ModelReply(text=json.dumps(dict(accepted=True, reason="固定支持响应", confidence=.9)),
                          input_tokens=0, output_tokens=0, model="fixed-demo", raw={"demo": True})


def main():
    print("固定响应工程演示，不进入效果报告")
    text = "冻结集合使用元组。"
    evidence = (EvidenceView(ref_id="demo-e1", text=text, source_id="demo-source",
                            content_hash=hashlib.sha256(text.encode()).hexdigest()),)
    result = verify_candidate(text, ("demo-e1",), evidence, FixedReview(),
        allowed_sources=("demo-source",), now=datetime.now(timezone.utc), source_run="demo-05")
    with TemporaryDirectory() as folder:
        path = Path(folder) / "knowledge.db"
        with SQLiteKnowledgeProvider(path) as provider:
            entry = provider.put_verified(result.candidate)
            assert provider.put_verified(result.candidate) == entry
        with SQLiteKnowledgeProvider(path) as provider:
            hit = provider.search("元组")[0]
            assert hit.knowledge_id == entry.knowledge_id
            print(json.dumps(dict(knowledge_id=hit.knowledge_id, score=hit.score,
                                  reopened=True), ensure_ascii=False))


if __name__ == "__main__":
    main()
