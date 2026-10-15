"""恢复、评分和报告共享的完整性校验；不充当数字签名。"""
import hashlib
import json
from pathlib import Path

from knowledge_gap_agent.contracts.config import RunConfig
from knowledge_gap_agent.runtime.models import RunResult
from knowledge_gap_agent.utils.canonical import sha256_hex
from .io import read_json
from .dataset import verify_snapshot


def validate_protocol(output):
    output = Path(output)
    protocol = read_json(output / "protocol.json")
    config = RunConfig.model_validate(protocol["base_config"])
    if config.config_hash != protocol["base_config_hash"]:
        raise ValueError("协议基础配置摘要不一致")
    verify_snapshot(output / "snapshot")
    metadata = read_json(output / "snapshot/audit/metadata.json")
    if metadata["dataset_hash"] != protocol["dataset_hash"]:
        raise ValueError("协议与快照数据摘要不一致")
    return protocol


def validate_run(record, output):
    if record["key"] != record["identity"]["key"] or record["phase"] != record["identity"]["phase"]:
        raise ValueError("运行身份不一致")
    effective = RunConfig.model_validate(record["effective_config"])
    if effective.config_hash != record["effective_config_hash"]:
        raise ValueError("实际配置摘要不一致")
    if record.get("result"):
        result = RunResult.model_validate(record["result"])
        if result.config != effective or result.config.variant.value != record["key"][1]:
            raise ValueError("运行与实际配置不一致")
        if result.config.prompt_hash != hashlib.sha256(result.system_prompt.encode("utf-8")).hexdigest():
            raise ValueError("实际系统提示词摘要失配")
        if sha256_hex(result.task.model_dump(mode="json")) != record["identity"]["task_hash"]:
            raise ValueError("运行输入摘要失配")
        # 轨迹存储自带规范JSON摘要；独立检查其内容绑定当前结果。
        relative = Path(record["trace_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("轨迹路径越界")
        envelope = json.loads((Path(output) / relative).read_text(encoding="utf-8"))
        if sha256_hex(envelope["result"]) != envelope["digest"] or envelope["result"] != record["result"]:
            raise ValueError("轨迹摘要或原始运行结果不一致")
    return record


def validate_grade(grade, run):
    if grade.get("key") != run["key"] or grade.get("identity") != run["identity"]:
        raise ValueError("评分身份与运行不一致")
    if grade.get("run_content_hash") != sha256_hex(run):
        raise ValueError("评分绑定的运行内容摘要失配")
    return grade
