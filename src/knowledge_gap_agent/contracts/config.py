from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from knowledge_gap_agent.utils.canonical import canonical_json, sha256_hex


class ExperimentVariant(StrEnum):
    E0 = "e0"
    E1 = "e1"
    E2 = "e2"
    E3 = "e3"


class RunConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    schema_version: str = Field(default="1.0", min_length=1)
    experiment_id: str = Field(min_length=1)
    variant: ExperimentVariant
    model_provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    temperature: float = Field(ge=0, le=2)
    max_steps: int = Field(ge=1)
    timeout_seconds: int = Field(ge=1)
    retry_limit: int = Field(ge=0)
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    toolset_version: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    corpus_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    random_seed: int

    @property
    def config_hash(self) -> str:
        return sha256_hex(self.model_dump(mode="json"))
