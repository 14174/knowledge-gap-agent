import json
import errno
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from knowledge_gap_agent.corpus.manifest import (
    SourceManifest,
    SourceManifestEntry,
    load_source_manifest,
    verify_sources,
)
from knowledge_gap_agent.corpus.normalize import content_hash


def entry_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "source_id": "source-1",
        "title": "固定来源",
        "source_url": "https://example.com/owner/repo/blob/" + "a" * 40 + "/docs/source.md",
        "repository": "owner/repo",
        "commit_sha": "a" * 40,
        "relative_path": "docs/source.md",
        "fetched_at": "2026-09-24T09:00:00+08:00",
        "content_hash": content_hash("正文\n"),
        "local_path": "sources/source.md",
    }
    payload.update(overrides)
    return payload


def write_manifest(tmp_path: Path, sources: list[dict[str, object]]) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({"schema_version": "1.0", "sources": sources}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def make_entry(**overrides: object) -> SourceManifestEntry:
    return SourceManifestEntry.model_validate(entry_payload(**overrides))


def test_load_source_manifest_reads_valid_manifest(tmp_path: Path) -> None:
    manifest = load_source_manifest(write_manifest(tmp_path, [entry_payload()]))

    assert manifest.schema_version == "1.0"
    assert isinstance(manifest.sources, tuple)
    assert manifest.sources[0].source_id == "source-1"
    assert manifest.sources[0].fetched_at.utcoffset() == timedelta(hours=8)


@pytest.mark.parametrize("commit_sha", ["main", "master", "HEAD", "a" * 39, "A" * 40])
def test_manifest_rejects_floating_or_invalid_revision(commit_sha: str) -> None:
    with pytest.raises(ValidationError, match="commit_sha"):
        make_entry(commit_sha=commit_sha)


def test_manifest_rejects_duplicate_source_id() -> None:
    with pytest.raises(ValidationError, match="source_id"):
        SourceManifest(sources=(make_entry(), make_entry()))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("relative_path", ""),
        ("relative_path", "../outside.md"),
        ("relative_path", "/absolute.md"),
        ("relative_path", "C:/absolute.md"),
        ("local_path", ""),
        ("local_path", "safe/../../outside.md"),
        ("local_path", "/absolute.md"),
        ("local_path", "C:\\absolute.md"),
    ],
)
def test_manifest_rejects_unsafe_paths(field: str, value: str) -> None:
    with pytest.raises(ValidationError, match=field):
        make_entry(**{field: value})


@pytest.mark.parametrize("field", ["relative_path", "local_path"])
@pytest.mark.parametrize(
    "value",
    [
        "docs\\source.md",
        ".",
        "docs/./source.md",
        "docs//source.md",
        "docs/source.md/",
        "docs /source.md",
        "docs./source.md",
        "docs/source.md ",
        "docs/source.md.",
        "CON",
        "prn.txt",
        "docs/AUX.md",
        "docs/nul.json",
        "COM1.log",
        "docs/com9.anything",
        "LPT1",
        "docs/lpt9.txt",
    ],
)
def test_manifest_rejects_non_portable_posix_paths(field: str, value: str) -> None:
    with pytest.raises(ValidationError, match=field):
        make_entry(**{field: value})


@pytest.mark.parametrize("field", ["relative_path", "local_path"])
@pytest.mark.parametrize("character", [*(chr(code) for code in range(32)), chr(127)])
def test_manifest_rejects_ascii_control_characters(field: str, character: str) -> None:
    with pytest.raises(ValidationError, match=field):
        make_entry(**{field: f"docs/a{character}b.md"})


@pytest.mark.parametrize("field", ["relative_path", "local_path"])
@pytest.mark.parametrize("character", list('<>:"|?*'))
def test_manifest_rejects_windows_forbidden_characters(field: str, character: str) -> None:
    with pytest.raises(ValidationError, match=field):
        make_entry(**{field: f"docs/a{character}b.md"})


@pytest.mark.parametrize("source_url", ["", "ftp://example.com/a", "https:///missing-host"])
def test_manifest_rejects_invalid_source_url(source_url: str) -> None:
    with pytest.raises(ValidationError, match="source_url"):
        make_entry(source_url=source_url)


@pytest.mark.parametrize("repository", ["owner", "/repo", "owner/", "owner/repo/extra"])
def test_manifest_rejects_invalid_repository(repository: str) -> None:
    with pytest.raises(ValidationError, match="repository"):
        make_entry(repository=repository)


def test_manifest_rejects_naive_fetched_at() -> None:
    with pytest.raises(ValidationError, match="fetched_at"):
        make_entry(fetched_at="2026-09-24T09:00:00")


@pytest.mark.parametrize("digest", ["0" * 63, "A" * 64])
def test_manifest_rejects_invalid_content_hash(digest: str) -> None:
    with pytest.raises(ValidationError, match="content_hash"):
        make_entry(content_hash=digest)


@pytest.mark.parametrize("text", ["not-json", "[1, 2, 3]"])
def test_load_source_manifest_rejects_invalid_document_without_echoing_content(
    tmp_path: Path, text: str
) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError) as error:
        load_source_manifest(path)

    assert text not in str(error.value)
    assert str(path) in str(error.value)


def test_verify_sources_reports_missing_file(tmp_path: Path) -> None:
    errors = verify_sources(SourceManifest(sources=(make_entry(),)), tmp_path)

    assert [error.error_type for error in errors] == ["missing_file"]
    assert errors[0].source_id == "source-1"
    assert errors[0].path == tmp_path / "sources/source.md"


def test_verify_sources_accumulates_errors_in_manifest_order(tmp_path: Path) -> None:
    unreadable = tmp_path / "sources" / "directory"
    unreadable.mkdir(parents=True)
    manifest = SourceManifest(
        sources=(
            make_entry(source_id="missing", local_path="sources/missing.md"),
            make_entry(source_id="unreadable", local_path="sources/directory"),
        )
    )

    errors = verify_sources(manifest, tmp_path)

    assert [(error.source_id, error.error_type) for error in errors] == [
        ("missing", "missing_file"),
        ("unreadable", "read_error"),
    ]


def test_verify_sources_accepts_matching_hash_and_normalized_crlf(tmp_path: Path) -> None:
    source = tmp_path / "sources" / "source.md"
    source.parent.mkdir()
    source.write_bytes(b"line one  \r\nline two\r\n")
    manifest = SourceManifest(
        sources=(make_entry(content_hash=content_hash("line one\nline two\n")),)
    )

    assert verify_sources(manifest, tmp_path) == []


def test_verify_sources_reports_hash_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "sources" / "source.md"
    source.parent.mkdir()
    source.write_text("实际内容\n", encoding="utf-8")
    manifest = SourceManifest(sources=(make_entry(content_hash="0" * 64),))

    errors = verify_sources(manifest, tmp_path)

    assert len(errors) == 1
    assert errors[0].error_type == "content_hash_mismatch"
    assert errors[0].expected == "0" * 64
    assert errors[0].actual == content_hash("实际内容\n")


def test_verify_sources_reports_bypassed_traversal_as_invalid_path(tmp_path: Path) -> None:
    entry = make_entry()
    unsafe_entry = entry.model_copy(update={"local_path": "../outside.md"})

    errors = verify_sources(SourceManifest(sources=(unsafe_entry,)), tmp_path)

    assert [error.error_type for error in errors] == ["invalid_path"]
    assert "POSIX" in errors[0].message


def test_verify_sources_reports_invalid_path_and_continues(tmp_path: Path) -> None:
    entry = make_entry()
    invalid = entry.model_copy(update={"source_id": "invalid", "local_path": "bad\0name.md"})
    missing = make_entry(source_id="missing", local_path="missing.md")

    errors = verify_sources(SourceManifest(sources=(invalid, missing)), tmp_path)

    assert [(error.source_id, error.error_type) for error in errors] == [
        ("invalid", "invalid_path"),
        ("missing", "missing_file"),
    ]


def test_verify_sources_reports_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("外部内容\n", encoding="utf-8")
    link = root / "source.md"
    try:
        link.symlink_to(outside)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314 or error.errno in {errno.EPERM, errno.EACCES}:
            pytest.skip(f"当前环境不允许创建符号链接: {type(error).__name__}")
        raise
    manifest = SourceManifest(sources=(make_entry(local_path="source.md"),))

    errors = verify_sources(manifest, root)

    assert [error.error_type for error in errors] == ["path_escape"]
    assert errors[0].path == link
    assert "根目录" in errors[0].message
