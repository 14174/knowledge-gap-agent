"""固定响应工程演示：验证写入后由新问题检索并引用同一知识编号。"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from knowledge_gap_agent.knowledge.store import SQLiteKnowledgeProvider
from knowledge_gap_agent.knowledge.verification import verify_candidate
from knowledge_gap_agent.runtime.models import EvidenceView, ModelReply


class FixedModel:
    def complete(self, system, payload, *, max_tokens=1800):
        if "text" in payload:
            result = dict(accepted=True, confidence=.9, reason="固定支持响应")
        else:
            result = dict(answer="可使用元组。", citations=[payload["evidence"][0]["ref_id"]])
        return ModelReply(text=json.dumps(result), input_tokens=0, output_tokens=0,
                          model="fixed-demo", raw={"demo": True})


def main():
    print("固定响应工程演示，不进入效果报告")
    text = "冻结集合使用元组。"
    evidence = (EvidenceView(ref_id="research-e1", text=text, source_id="demo-source",
                            content_hash=hashlib.sha256(text.encode()).hexdigest()),)
    model = FixedModel()
    result = verify_candidate(text, ("research-e1",), evidence, model,
        allowed_sources=("demo-source",), now=datetime.now(timezone.utc), source_run="demo-08-first")
    with TemporaryDirectory() as folder:
        with SQLiteKnowledgeProvider(Path(folder) / "knowledge.db") as provider:
            entry = provider.put_verified(result.candidate)
            hits = provider.search("冻结集合应该选什么容器？")
            reply = model.complete("请引用证据回答。", {"question": "冻结集合应该选什么容器？",
                "evidence": [hit.as_evidence().model_dump(mode="json") for hit in hits]})
            answer = json.loads(reply.text)
            assert entry.knowledge_id in answer["citations"]
            print(json.dumps(answer, ensure_ascii=False))


if __name__ == "__main__":
    main()
