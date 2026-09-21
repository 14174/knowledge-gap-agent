import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """将 JSON 兼容对象按键排序并紧凑序列化，拒绝非有限数值。"""
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def sha256_hex(value: Any) -> str:
    """规范化 JSON 兼容对象后计算 UTF-8 SHA-256 十六进制摘要。"""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
