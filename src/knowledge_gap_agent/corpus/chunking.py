import re
from dataclasses import dataclass

from knowledge_gap_agent.corpus.models import CorpusChunk, SourceDocument
from knowledge_gap_agent.corpus.normalize import content_hash
from knowledge_gap_agent.utils.canonical import sha256_hex


_ATX_HEADING = re.compile(r"^(#{1,6}) +(.*?)\s*$")
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_FENCE_CLOSE = re.compile(r"^ {0,3}(`+|~+)[ \t]*$")


@dataclass(frozen=True)
class _Paragraph:
    text: str
    start_line: int
    end_line: int


def _make_chunk(
    document: SourceDocument,
    heading_path: tuple[str, ...],
    paragraphs: list[_Paragraph],
) -> CorpusChunk:
    text = "\n\n".join(paragraph.text for paragraph in paragraphs)
    chunk_hash = content_hash(text)
    start_line = paragraphs[0].start_line
    end_line = paragraphs[-1].end_line
    chunk_id = sha256_hex(
        {
            "source_id": document.source_id,
            "heading_path": list(heading_path),
            "start_line": start_line,
            "end_line": end_line,
            "content_hash": chunk_hash,
        }
    )
    return CorpusChunk(
        chunk_id=chunk_id,
        source_id=document.source_id,
        heading_path=heading_path,
        start_line=start_line,
        end_line=end_line,
        text=text,
        token_terms=(),
        content_hash=chunk_hash,
        claim_ids=(),
    )


def _chunk_section(
    document: SourceDocument,
    heading_path: tuple[str, ...],
    paragraphs: list[_Paragraph],
    max_chars: int,
) -> list[CorpusChunk]:
    chunks: list[CorpusChunk] = []
    group: list[_Paragraph] = []
    group_length = 0

    for paragraph in paragraphs:
        separator_length = 2 if group else 0
        if group and group_length + separator_length + len(paragraph.text) > max_chars:
            chunks.append(_make_chunk(document, heading_path, group))
            group = []
            group_length = 0
            separator_length = 0
        group.append(paragraph)
        group_length += separator_length + len(paragraph.text)

    if group:
        chunks.append(_make_chunk(document, heading_path, group))
    return chunks


def chunk_markdown(document: SourceDocument, max_chars: int = 1200) -> list[CorpusChunk]:
    """按 Markdown 标题和段落边界生成确定性语料块。"""
    if max_chars < 1:
        raise ValueError("max_chars must be greater than or equal to 1")

    chunks: list[CorpusChunk] = []
    heading_path: tuple[str, ...] = ()
    heading_stack: list[tuple[int, str]] = []
    paragraphs: list[_Paragraph] = []
    paragraph_lines: list[str] = []
    paragraph_start = 0
    fence: tuple[str, int] | None = None

    def finish_paragraph(end_line: int) -> None:
        nonlocal paragraph_lines, paragraph_start
        if paragraph_lines:
            paragraphs.append(
                _Paragraph(
                    text="\n".join(paragraph_lines),
                    start_line=paragraph_start,
                    end_line=end_line,
                )
            )
            paragraph_lines = []
            paragraph_start = 0

    def finish_section() -> None:
        nonlocal paragraphs
        chunks.extend(_chunk_section(document, heading_path, paragraphs, max_chars))
        paragraphs = []

    lines = document.content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    last_real_line = len(lines) - (1 if lines[-1] == "" else 0)
    for line_number, raw_line in enumerate(lines, start=1):
        if line_number > last_real_line:
            continue
        line = raw_line.rstrip()
        if fence is not None:
            paragraph_lines.append(line)
            closing = _FENCE_CLOSE.match(raw_line)
            if closing:
                marker = closing.group(1)
                if marker[0] == fence[0] and len(marker) >= fence[1]:
                    fence = None
            continue

        opening = _FENCE_OPEN.match(raw_line)
        if opening:
            if not paragraph_lines:
                paragraph_start = line_number
            paragraph_lines.append(line)
            marker = opening.group(1)
            fence = (marker[0], len(marker))
            continue

        heading = _ATX_HEADING.match(raw_line)
        if heading:
            finish_paragraph(line_number - 1)
            finish_section()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            heading_stack = [item for item in heading_stack if item[0] < level]
            if title:
                heading_stack.append((level, title))
            heading_path = tuple(item[1] for item in heading_stack)
        elif not line.strip():
            finish_paragraph(line_number - 1)
        else:
            if not paragraph_lines:
                paragraph_start = line_number
            paragraph_lines.append(line)

    finish_paragraph(last_real_line)
    finish_section()
    return chunks


__all__ = ["chunk_markdown"]
