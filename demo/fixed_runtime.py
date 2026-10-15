"""演示专用固定响应，令牌仅为测试输入，不代表服务用量或模型效果。"""
import hashlib
import json

from knowledge_gap_agent.contracts.config import RunConfig
from knowledge_gap_agent.runtime.loop import DEFAULT_SYSTEM_PROMPT
from knowledge_gap_agent.runtime.models import EvidenceView, ModelReply


def build_config() -> RunConfig:
    return RunConfig(experiment_id="fixed-demo", variant="e0", model_provider="fixed-demo",
        model_name="fixed-demo", model_revision="fixed-response", temperature=0, max_steps=3,
        timeout_seconds=1, retry_limit=0,
        prompt_hash=hashlib.sha256(DEFAULT_SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
        toolset_version="demo-v1", dataset_version="demo-only", corpus_hash="0" * 64, random_seed=0)


class FixedModel:
    def __init__(self, config: RunConfig, actions: tuple[str | dict, ...]):
        self.config = config
        self._actions = iter(actions)

    def complete(self, system: str, payload: dict, *, max_tokens=1800) -> ModelReply:
        action = next(self._actions)
        text = action if isinstance(action, str) else json.dumps(action, ensure_ascii=False)
        return ModelReply(text=text, input_tokens=0, output_tokens=0, model="fixed-demo", raw={"fixed_demo": action})


def research(query: str) -> tuple[EvidenceView, ...]:
    text = "冻结模型的集合字段使用元组，JSON 输出仍为数组。"
    return (EvidenceView(ref_id="demo-1", text=text, source_id="固定演示资料",
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()),)


def success_model(config: RunConfig) -> FixedModel:
    return FixedModel(config, ({"kind": "research", "query": "冻结模型集合"},
        {"kind": "answer", "answer": "使用元组保存集合。", "citations": ["demo-1"]}))
