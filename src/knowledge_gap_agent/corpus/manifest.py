import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from knowledge_gap_agent.corpus.normalize import content_hash

_LOWER_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_LOWER_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_WINDOWS_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}
_WINDOWS_FORBIDDEN_CHARACTERS = set('<>:"|?*')


def _validate_relative_path(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("路径不能为空")
    if "\\" in value:
        raise ValueError("路径必须使用 POSIX 分隔符")
    raw_parts = value.split("/")
    if any(not part for part in raw_parts):
        raise ValueError("路径不能包含空组件")
    posix = PurePosixPath(value)
    if posix.is_absolute() or re.match(r"^[A-Za-z]:", value):
        raise ValueError("路径必须为相对路径")
    for part in raw_parts:
        if any(ord(character) < 32 or ord(character) == 127 for character in part):
            raise ValueError("路径组件不能包含 ASCII 控制字符")
        if any(character in _WINDOWS_FORBIDDEN_CHARACTERS for character in part):
            raise ValueError("路径组件不能包含 Windows 禁止字符")
        if part in {".", ".."}:
            raise ValueError("路径不能包含当前或上级目录跳转")
        if part.endswith((" ", ".")):
            raise ValueError("路径组件不能以空格或点结尾")
        if part.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
            raise ValueError("路径组件不能使用 Windows 保留设备名")
    return value


class SourceManifestEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_url: str
    repository: str
    commit_sha: str
    relative_path: str
    fetched_at: datetime
    content_hash: str
    local_path: str

    @field_validator("commit_sha")
    @classmethod
    def validate_commit_sha(cls, value: str) -> str:
        if not _LOWER_HEX_40.fullmatch(value):
            raise ValueError("commit_sha 必须是 40 位小写十六进制提交摘要，不能使用浮动引用")
        return value

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        if not _LOWER_HEX_64.fullmatch(value):
            raise ValueError("content_hash 必须是 64 位小写十六进制摘要")
        return value

    @field_validator("relative_path", "local_path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _validate_relative_path(value)

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("source_url 必须是包含主机名的 HTTP(S) URL")
        return value

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, value: str) -> str:
        if not _REPOSITORY.fullmatch(value):
            raise ValueError("repository 必须使用 owner/name 格式")
        return value

    @field_validator("fetched_at")
    @classmethod
    def validate_fetched_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fetched_at 必须包含时区")
        return value


class SourceManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    sources: tuple[SourceManifestEntry, ...]

    @model_validator(mode="after")
    def validate_unique_source_ids(self) -> "SourceManifest":
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source_id 必须唯一")
        return self


class SourceVerificationError(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    error_type: Literal[
        "missing_file", "read_error", "content_hash_mismatch", "invalid_path", "path_escape"
    ]
    path: Path
    expected: str | None = None
    actual: str | None = None
    message: str


def load_source_manifest(path: str | Path) -> SourceManifest:
    manifest_path = Path(path)
    try:
        raw = manifest_path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取来源清单 {manifest_path}: {type(error).__name__}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"来源清单 {manifest_path} 的顶层必须是对象")
    return SourceManifest.model_validate(payload)


def verify_sources(manifest: SourceManifest, root: str | Path) -> list[SourceVerificationError]:
    root_path = Path(root).resolve()
    errors: list[SourceVerificationError] = []
    for source in manifest.sources:
        try:
            _validate_relative_path(source.local_path)
        except ValueError:
            candidate = root_path.joinpath(*PurePosixPath(source.local_path).parts)
            errors.append(
                SourceVerificationError(
                    source_id=source.source_id,
                    error_type="invalid_path",
                    path=candidate,
                    message="local_path 不符合安全 POSIX 相对路径约束",
                )
            )
            continue
        candidate = root_path.joinpath(*PurePosixPath(source.local_path).parts)
        try:
            resolved = candidate.resolve()
        except ValueError as error:
            errors.append(
                SourceVerificationError(
                    source_id=source.source_id,
                    error_type="invalid_path",
                    path=candidate,
                    message=f"local_path 无法解析: {type(error).__name__}",
                )
            )
            continue
        except (OSError, RuntimeError) as error:
            errors.append(
                SourceVerificationError(
                    source_id=source.source_id,
                    error_type="read_error",
                    path=candidate,
                    message=f"无法解析来源文件路径: {type(error).__name__}",
                )
            )
            continue
        if not resolved.is_relative_to(root_path):
            errors.append(
                SourceVerificationError(
                    source_id=source.source_id,
                    error_type="path_escape",
                    path=candidate,
                    message="local_path 解析结果超出根目录",
                )
            )
            continue
        try:
            exists = resolved.exists()
            is_file = resolved.is_file() if exists else False
        except ValueError as error:
            errors.append(
                SourceVerificationError(
                    source_id=source.source_id,
                    error_type="invalid_path",
                    path=resolved,
                    message=f"来源文件路径无效: {type(error).__name__}",
                )
            )
            continue
        except (OSError, RuntimeError) as error:
            errors.append(
                SourceVerificationError(
                    source_id=source.source_id,
                    error_type="read_error",
                    path=resolved,
                    message=f"无法检查来源文件状态: {type(error).__name__}",
                )
            )
            continue
        if not exists:
            errors.append(
                SourceVerificationError(
                    source_id=source.source_id,
                    error_type="missing_file",
                    path=resolved,
                    message="来源文件不存在",
                )
            )
            continue
        if not is_file:
            errors.append(
                SourceVerificationError(
                    source_id=source.source_id,
                    error_type="read_error",
                    path=resolved,
                    message="来源路径不是普通文件",
                )
            )
            continue
        try:
            actual = content_hash(resolved.read_text(encoding="utf-8"))
        except ValueError as error:
            errors.append(
                SourceVerificationError(
                    source_id=source.source_id,
                    error_type="invalid_path",
                    path=resolved,
                    message=f"来源文件路径无效: {type(error).__name__}",
                )
            )
            continue
        except (OSError, UnicodeError, RuntimeError) as error:
            errors.append(
                SourceVerificationError(
                    source_id=source.source_id,
                    error_type="read_error",
                    path=resolved,
                    message=f"无法读取来源文件: {type(error).__name__}",
                )
            )
            continue
        if actual != source.content_hash:
            errors.append(
                SourceVerificationError(
                    source_id=source.source_id,
                    error_type="content_hash_mismatch",
                    path=resolved,
                    expected=source.content_hash,
                    actual=actual,
                    message="来源文件内容哈希不匹配",
                )
            )
    return errors


__all__ = [
    "SourceManifest",
    "SourceManifestEntry",
    "SourceVerificationError",
    "load_source_manifest",
    "verify_sources",
]
