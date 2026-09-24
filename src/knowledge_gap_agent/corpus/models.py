from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from knowledge_gap_agent.corpus.normalize import content_hash


NonEmptyString = Annotated[str, Field(min_length=1)]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
CommitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]


def _reject_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


def _reject_blank_items(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if any(not value.strip() for value in values):
        raise ValueError(f"{field_name} must not contain blank strings")
    return values


def _require_timezone(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone information")
    return value


class SourceDocument(BaseModel):
    """固定版本的来源文档。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: NonEmptyString
    title: NonEmptyString
    source_url: NonEmptyString
    repository: NonEmptyString
    commit_sha: CommitSha
    relative_path: NonEmptyString
    fetched_at: datetime
    content_hash: Sha256Hex
    content: NonEmptyString

    @field_validator("source_id", "title", "source_url", "repository", "relative_path", "content")
    @classmethod
    def reject_blank_strings(cls, value: str, info: Any) -> str:
        return _reject_blank(value, info.field_name)

    @field_validator("fetched_at")
    @classmethod
    def require_fetched_at_timezone(cls, value: datetime) -> datetime:
        return _require_timezone(value, "fetched_at")

    @model_validator(mode="after")
    def validate_content_hash(self):
        if self.content_hash != content_hash(self.content):
            raise ValueError("content_hash does not match normalized content")
        return self


class CorpusChunk(BaseModel):
    """带原始行号和证据关联的语料块。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: NonEmptyString
    source_id: NonEmptyString
    heading_path: tuple[NonEmptyString, ...]
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    text: NonEmptyString
    token_terms: tuple[NonEmptyString, ...]
    content_hash: Sha256Hex
    claim_ids: tuple[NonEmptyString, ...]

    @field_validator("chunk_id", "source_id", "text")
    @classmethod
    def reject_blank_strings(cls, value: str, info: Any) -> str:
        return _reject_blank(value, info.field_name)

    @field_validator("heading_path", "token_terms", "claim_ids")
    @classmethod
    def reject_blank_list_items(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _reject_blank_items(value, info.field_name)

    @model_validator(mode="after")
    def validate_range_and_hash(self):
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        if self.content_hash != content_hash(self.text):
            raise ValueError("content_hash does not match normalized text")
        return self


class Claim(BaseModel):
    """由语料块支持且可带时效和冲突关系的知识主张。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: NonEmptyString
    statement: NonEmptyString
    evidence_chunk_ids: tuple[NonEmptyString, ...]
    valid_from: datetime | None
    valid_until: datetime | None
    conflicts_with: tuple[NonEmptyString, ...]

    @field_validator("claim_id", "statement")
    @classmethod
    def reject_blank_strings(cls, value: str, info: Any) -> str:
        return _reject_blank(value, info.field_name)

    @field_validator("evidence_chunk_ids", "conflicts_with")
    @classmethod
    def reject_blank_list_items(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _reject_blank_items(value, info.field_name)

    @field_validator("valid_from", "valid_until")
    @classmethod
    def require_validity_timezone(
        cls, value: datetime | None, info: Any
    ) -> datetime | None:
        if value is None:
            return None
        return _require_timezone(value, info.field_name)

    @model_validator(mode="after")
    def validate_conflicts_and_validity(self):
        if self.claim_id in self.conflicts_with:
            raise ValueError("conflicts_with cannot contain claim_id itself")
        if self.valid_from is not None and self.valid_until is not None:
            if self.valid_until < self.valid_from:
                raise ValueError("valid_until must not be earlier than valid_from")
        return self
