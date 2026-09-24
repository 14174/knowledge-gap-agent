import pytest

from knowledge_gap_agent.retrieval.tokenizer import tokenize


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("知识缺口", ["知识", "识缺", "缺口"]),
        ("中", ["中"]),
        ("BM25 config_hash 2026", ["bm25", "config_hash", "2026"]),
        ("知识BM25缺口", ["知识", "bm25", "缺口"]),
        ("甲乙，丙丁", ["甲乙", "丙丁"]),
        ("㐀㐁，𠀀𠀁。﨎﨏", ["㐀㐁", "𠀀𠀁", "﨎﨏"]),
        ("𠀀", ["𠀀"]),
        ("，。 \t\n！", []),
        ("", []),
    ],
)
def test_tokenize_uses_stable_script_aware_terms(
    text: str, expected: list[str]
) -> None:
    assert tokenize(text) == expected
