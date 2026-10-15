"""固定响应工程演示：三类充分性与低置信度研究门禁。"""
import json

from knowledge_gap_agent.knowledge.sufficiency import assess
from knowledge_gap_agent.runtime.models import ModelReply


class FixedAssessment:
    def __init__(self, label, confidence):
        self.label, self.confidence = label, confidence

    def complete(self, system, payload, *, max_tokens=1800):
        result = dict(label=self.label, confidence=self.confidence, reason="固定演示判断",
                      missing_claims=[] if self.label == "enough" else ["需补充容器约束"],
                      stale_ids=[], conflict_ids=[])
        return ModelReply(text=json.dumps(result), input_tokens=0, output_tokens=0,
                          model="fixed-demo", raw={"demo": True})


def main():
    print("固定响应工程演示，不进入效果报告")
    for label, confidence in (("enough", .9), ("partial", .9), ("missing", .9), ("enough", .7)):
        decision = assess("为何选择元组？", (), FixedAssessment(label, confidence))
        assert decision.needs_research == (label != "enough" or confidence < .8)
        print(decision.model_dump_json(exclude={"reply"}))


if __name__ == "__main__":
    main()
