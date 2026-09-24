import hashlib

from knowledge_gap_agent.corpus.normalize import canonical_json, content_hash, normalize_text


def test_normalize_text_unifies_newlines_and_trailing_spaces() -> None:
    assert normalize_text("标题  \r\n正文\t\r末行   ") == "标题\n正文\n末行\n"


def test_normalize_text_keeps_exactly_one_terminal_newline() -> None:
    assert normalize_text("正文\n\n") == "正文\n"


def test_content_hash_uses_normalized_utf8_text() -> None:
    expected = hashlib.sha256("标题\n正文\n".encode("utf-8")).hexdigest()
    assert content_hash("标题  \r\n正文\t") == expected


def test_canonical_json_is_stable_across_mapping_key_order() -> None:
    assert canonical_json({"b": 2, "a": 1}) == canonical_json({"a": 1, "b": 2})
