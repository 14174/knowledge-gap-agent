"""固定响应工程演示：越界引用和语义不支持均拒绝。"""
import hashlib
import json
from datetime import datetime, timezone

from knowledge_gap_agent.knowledge.verification import verify_candidate
from knowledge_gap_agent.runtime.models import EvidenceView, ModelReply


class FixedRejection:
    def complete(self, system, payload, *, max_tokens=1800):
        return ModelReply(text=json.dumps(dict(accepted=False, reason="引文未支持候选扩展", confidence=.95)),
                          input_tokens=0, output_tokens=0, model="fixed-demo", raw={"demo": True})


def main():
    print("固定响应工程演示，不进入效果报告")
    text = "元组不可变。"
    evidence = (EvidenceView(ref_id="demo-e1", text=text, source_id="demo-source",
                            content_hash=hashlib.sha256(text.encode()).hexdigest()),)
    for refs in (("outside",), ("demo-e1",)):
        result = verify_candidate("元组总比列表更快。", refs, evidence, FixedRejection(),
            allowed_sources=("demo-source",), now=datetime.now(timezone.utc), source_run="demo-07")
        assert not result.accepted and result.candidate is None
        print(result.model_dump_json())


if __name__ == "__main__":
    main()
