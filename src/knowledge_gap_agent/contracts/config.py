from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from knowledge_gap_agent.utils.canonical import canonical_json, sha256_hex


class ExperimentVariant(StrEnum):
    E0 = "E0"
    E1 = "E1"
    E2 = "E2"
    E3 = "E3"


class RunConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    schema_version: str = "1.0"
    experiment_id: str
    variant: ExperimentVariant
    model_provider: str
    model_name: str
    model_revision: str
    temperature: float = Field(ge=0, le=2)
    max_steps: int = Field(ge=1)
    timeout_seconds: int = Field(ge=1)
    retry_limit: int = Field(ge=0)
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    toolset_version: str
    dataset_version: str
    corpus_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    random_seed: int

    @property
    def config_hash(self) -> str:
        return sha256_hex(canonical_json(self.model_dump(mode="json")))
