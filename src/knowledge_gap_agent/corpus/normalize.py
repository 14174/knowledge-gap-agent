import hashlib

from knowledge_gap_agent.utils.canonical import canonical_json


def normalize_text(text: str) -> str:
    """统一换行并移除行尾空白，结果恰有一个终止换行。"""
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in unified.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


def content_hash(text: str) -> str:
    """计算规范化 UTF-8 文本的 SHA-256 摘要。"""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


__all__ = ["canonical_json", "content_hash", "normalize_text"]
