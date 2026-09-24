from datetime import UTC, datetime

import pytest

from knowledge_gap_agent.corpus.chunking import chunk_markdown
from knowledge_gap_agent.corpus.models import SourceDocument
from knowledge_gap_agent.corpus.normalize import content_hash
from knowledge_gap_agent.utils.canonical import sha256_hex


def make_document(content: str, *, source_id: str = "source-1") -> SourceDocument:
    return SourceDocument(
        source_id=source_id,
        title="示例来源",
        source_url="https://example.com/source",
        repository="owner/repository",
        commit_sha="a" * 40,
        relative_path="docs/source.md",
        fetched_at=datetime(2026, 9, 24, tzinfo=UTC),
        content_hash=content_hash(content),
        content=content,
    )


def test_chunk_markdown_keeps_heading_path_line_range_and_combines_section_paragraphs() -> None:
    document = make_document(
        "# 一级\n\n正文一\n\n第二段\n\n## 二级\n\n正文二\n"
    )

    chunks = chunk_markdown(document)

    assert [
        (chunk.heading_path, chunk.start_line, chunk.end_line, chunk.text)
        for chunk in chunks
    ] == [
        (("一级",), 3, 5, "正文一\n\n第二段"),
        (("一级", "二级"), 9, 9, "正文二"),
    ]


def test_heading_level_fallback_replaces_deeper_heading_path() -> None:
    document = make_document(
        "# 一级\n\n## 二级甲\n\n内容甲\n\n### 三级\n\n内容乙\n\n## 二级乙\n\n内容丙\n"
    )

    chunks = chunk_markdown(document)

    assert [chunk.heading_path for chunk in chunks] == [
        ("一级", "二级甲"),
        ("一级", "二级甲", "三级"),
        ("一级", "二级乙"),
    ]


def test_skipped_heading_level_still_replaces_same_level_heading() -> None:
    document = make_document(
        "# 一级\n\n### 三级甲\n\n内容甲\n\n### 三级乙\n\n内容乙\n"
    )

    chunks = chunk_markdown(document)

    assert [(chunk.heading_path, chunk.text) for chunk in chunks] == [
        (("一级", "三级甲"), "内容甲"),
        (("一级", "三级乙"), "内容乙"),
    ]


def test_skipped_heading_levels_support_deeper_heading_and_level_fallback() -> None:
    document = make_document(
        "# 一级\n\n### 三级\n\n#### 五级前一层\n\n内容甲\n\n## 二级\n\n内容乙\n\n#### 四级\n\n内容丙\n"
    )

    chunks = chunk_markdown(document)

    assert [(chunk.heading_path, chunk.text) for chunk in chunks] == [
        (("一级", "三级", "五级前一层"), "内容甲"),
        (("一级", "二级"), "内容乙"),
        (("一级", "二级", "四级"), "内容丙"),
    ]


def test_empty_sections_do_not_produce_chunks() -> None:
    document = make_document("# 空章节\n\n## 仍为空\n\n# 有内容\n\n正文\n")

    chunks = chunk_markdown(document)

    assert len(chunks) == 1
    assert chunks[0].heading_path == ("有内容",)
    assert chunks[0].text == "正文"


def test_empty_atx_heading_is_a_section_boundary_without_blank_path_item() -> None:
    document = make_document("# 一级\n\n正文甲\n\n#   \n\n正文乙\n")

    chunks = chunk_markdown(document)

    assert [(chunk.heading_path, chunk.text) for chunk in chunks] == [
        (("一级",), "正文甲"),
        ((), "正文乙"),
    ]


def test_chunk_markdown_is_deterministic() -> None:
    document = make_document("# 标题\n\n同一段内容\n")

    assert chunk_markdown(document) == chunk_markdown(document)


def test_long_section_groups_only_at_paragraph_boundaries() -> None:
    document = make_document("# 标题\n\naaaa\n\nbbbb\n\ncc\n")

    chunks = chunk_markdown(document, max_chars=10)

    assert [(chunk.text, chunk.start_line, chunk.end_line) for chunk in chunks] == [
        ("aaaa\n\nbbbb", 3, 5),
        ("cc", 7, 7),
    ]


def test_single_paragraph_may_exceed_max_chars_without_hard_split() -> None:
    document = make_document("# 标题\n\n一段超过限制的正文\n")

    chunks = chunk_markdown(document, max_chars=3)

    assert len(chunks) == 1
    assert chunks[0].text == "一段超过限制的正文"
    assert (chunks[0].start_line, chunks[0].end_line) == (3, 3)


def test_content_before_first_heading_uses_empty_heading_path() -> None:
    document = make_document("前言第一行\n前言第二行\n\n# 正文\n\n章节内容\n")

    chunks = chunk_markdown(document)

    assert [(chunk.heading_path, chunk.text) for chunk in chunks] == [
        ((), "前言第一行\n前言第二行"),
        (("正文",), "章节内容"),
    ]


def test_only_atx_headings_with_one_to_six_hashes_and_space_are_recognized() -> None:
    document = make_document(
        "#合法但不是标题\n\n##\t制表符也不是标题\n\n####### 也不是标题\n\n###### 六级\n\n正文\n"
    )

    chunks = chunk_markdown(document)

    assert [(chunk.heading_path, chunk.text) for chunk in chunks] == [
        ((), "#合法但不是标题\n\n##\t制表符也不是标题\n\n####### 也不是标题"),
        (("六级",), "正文"),
    ]


@pytest.mark.parametrize(
    "markdown",
    [
        "# 章节\n\n```python\n# 伪标题\n\nprint('ok')\n````\n\n## 子节\n\n正文\n",
        "# 章节\n\n~~~python\n# 伪标题\n\nprint('ok')\n~~~~\n\n## 子节\n\n正文\n",
    ],
)
def test_fenced_code_keeps_pseudo_headings_as_body(markdown: str) -> None:
    chunks = chunk_markdown(make_document(markdown))

    assert [(chunk.heading_path, chunk.text) for chunk in chunks] == [
        (
            ("章节",),
            "```python\n# 伪标题\n\nprint('ok')\n````"
            if markdown.startswith("# 章节\n\n```")
            else "~~~python\n# 伪标题\n\nprint('ok')\n~~~~",
        ),
        (("章节", "子节"), "正文"),
    ]


def test_short_or_different_fence_does_not_close_open_fence() -> None:
    document = make_document(
        "# 章节\n\n````python\n# 伪标题甲\n```\n## 伪标题乙\n~~~~\n### 伪标题丙\n````\n\n## 子节\n\n正文\n"
    )

    chunks = chunk_markdown(document)

    assert [(chunk.heading_path, chunk.text) for chunk in chunks] == [
        (
            ("章节",),
            "````python\n# 伪标题甲\n```\n## 伪标题乙\n~~~~\n### 伪标题丙\n````",
        ),
        (("章节", "子节"), "正文"),
    ]


def test_unclosed_fence_treats_all_remaining_lines_as_body() -> None:
    document = make_document(
        "# 章节\n\n   ~~~text\n## 伪标题\n\n围栏正文\n# 仍是伪标题\n"
    )

    chunks = chunk_markdown(document)

    assert [(chunk.heading_path, chunk.text) for chunk in chunks] == [
        (
            ("章节",),
            "   ~~~text\n## 伪标题\n\n围栏正文\n# 仍是伪标题",
        )
    ]


def test_unclosed_fence_is_identical_with_or_without_terminal_newline() -> None:
    without_newline = chunk_markdown(make_document("# H\n\n```\nbody"))[0]
    with_newline = chunk_markdown(make_document("# H\n\n```\nbody\n"))[0]

    assert (
        without_newline.start_line,
        without_newline.end_line,
        without_newline.text,
        without_newline.content_hash,
        without_newline.chunk_id,
    ) == (
        with_newline.start_line,
        with_newline.end_line,
        with_newline.text,
        with_newline.content_hash,
        with_newline.chunk_id,
    )


def test_regular_body_is_identical_with_or_without_terminal_newline() -> None:
    without_newline = chunk_markdown(make_document("# H\n\nbody"))[0]
    with_newline = chunk_markdown(make_document("# H\n\nbody\n"))[0]

    assert without_newline == with_newline


@pytest.mark.parametrize("max_chars", [0, -1])
def test_max_chars_must_be_positive(max_chars: int) -> None:
    with pytest.raises(ValueError, match="max_chars"):
        chunk_markdown(make_document("正文\n"), max_chars=max_chars)


def test_chunk_hash_and_id_are_derived_from_canonical_identity_fields() -> None:
    chunk = chunk_markdown(make_document("# 标题\n\n正文\n"))[0]

    assert chunk.content_hash == content_hash("正文")
    assert chunk.chunk_id == sha256_hex(
        {
            "source_id": "source-1",
            "heading_path": ["标题"],
            "start_line": 3,
            "end_line": 3,
            "content_hash": chunk.content_hash,
        }
    )
    assert chunk.token_terms == ()
    assert chunk.claim_ids == ()


def test_chunk_identity_matches_literal_canary_values() -> None:
    chunk = chunk_markdown(make_document("# 标题\n\n正文\n"))[0]

    assert chunk.content_hash == "2373f217b111245d33d920bd1e0e7788174034fdee84050c0c34c7f9cb0a0bf4"
    assert chunk.chunk_id == "d22b82018183a61ad00ebbf364b1ac8d94d5b86ce96943ade227b95a00c8eccf"


def test_newline_styles_produce_equivalent_chunks() -> None:
    lf = chunk_markdown(make_document("# 标题\n\n正文甲\n正文乙\n"))
    crlf = chunk_markdown(make_document("# 标题\r\n\r\n正文甲\r\n正文乙\r\n"))
    cr = chunk_markdown(make_document("# 标题\r\r正文甲\r正文乙\r"))

    assert lf == crlf == cr


def test_paragraph_join_at_max_chars_stays_together_and_one_over_splits() -> None:
    document = make_document("# 标题\n\naaaa\n\nbbbb\n")

    assert [chunk.text for chunk in chunk_markdown(document, max_chars=10)] == [
        "aaaa\n\nbbbb"
    ]
    assert [chunk.text for chunk in chunk_markdown(document, max_chars=9)] == [
        "aaaa",
        "bbbb",
    ]


def test_repeated_heading_and_body_at_different_lines_have_unique_chunk_ids() -> None:
    document = make_document("# 标题\n\n正文\n\n# 标题\n\n正文\n")

    chunks = chunk_markdown(document)

    assert len(chunks) == 2
    assert chunks[0].content_hash == chunks[1].content_hash
    assert chunks[0].chunk_id != chunks[1].chunk_id


def test_chunk_hash_and_id_change_when_content_changes() -> None:
    original = chunk_markdown(make_document("# 标题\n\n正文甲\n"))[0]
    changed = chunk_markdown(make_document("# 标题\n\n正文乙\n"))[0]

    assert changed.content_hash != original.content_hash
    assert changed.chunk_id != original.chunk_id


def test_chunk_id_changes_when_line_range_changes_but_hash_does_not() -> None:
    original = chunk_markdown(make_document("# 标题\n\n正文\n"))[0]
    shifted = chunk_markdown(make_document("# 标题\n\n\n正文\n"))[0]

    assert shifted.content_hash == original.content_hash
    assert shifted.start_line != original.start_line
    assert shifted.chunk_id != original.chunk_id
