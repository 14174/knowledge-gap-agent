from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from knowledge_gap_agent.utils.canonical import sha256_hex


NonEmptyString = Annotated[str, Field(min_length=1)]


def compute_environment_hash(
    environment_id: str,
    visible_chunk_ids: tuple[str, ...] | list[str],
    research_chunk_ids: tuple[str, ...] | list[str],
    excluded_chunk_ids: tuple[str, ...] | list[str],
) -> str:
    return sha256_hex({
        "environment_id": environment_id,
        "visible_chunk_ids": sorted(visible_chunk_ids),
        "research_chunk_ids": sorted(research_chunk_ids),
        "excluded_chunk_ids": sorted(excluded_chunk_ids),
    })


class KnowledgeEnvironment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    environment_id: NonEmptyString
    visible_chunk_ids: tuple[NonEmptyString, ...]
    research_chunk_ids: tuple[NonEmptyString, ...]
    excluded_chunk_ids: tuple[NonEmptyString, ...]
    environment_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("environment_id")
    @classmethod
    def reject_blank_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("environment_id must not be blank")
        return value

    @field_validator("visible_chunk_ids", "research_chunk_ids", "excluded_chunk_ids")
    @classmethod
    def validate_chunk_ids(cls, values: tuple[str, ...], info: Any) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} must not contain blank strings")
        if len(values) != len(set(values)):
            raise ValueError(f"{info.field_name} must not contain duplicate values")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def validate_disjoint_sets_and_hash(self):
        groups = (set(self.visible_chunk_ids), set(self.research_chunk_ids),
                  set(self.excluded_chunk_ids))
        if any(groups[left] & groups[right] for left, right in ((0, 1), (0, 2), (1, 2))):
            raise ValueError("chunk collections must be pairwise disjoint")
        expected = compute_environment_hash(
            self.environment_id, self.visible_chunk_ids,
            self.research_chunk_ids, self.excluded_chunk_ids,
        )
        if self.environment_hash != expected:
            raise ValueError("environment_hash does not match environment contents")
        return self


class ValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: NonEmptyString
    case_id: NonEmptyString
    message: NonEmptyString
    refs: tuple[NonEmptyString, ...] = ()
