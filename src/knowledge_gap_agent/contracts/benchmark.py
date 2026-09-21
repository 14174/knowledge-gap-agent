from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CaseCategory(StrEnum):
    """基准样例的本地知识缺口分类。"""
    LOCAL_SUFFICIENT = "local_sufficient"
    LOCAL_PARTIAL = "local_partial"
    LOCAL_MISSING = "local_missing"
    OUTDATED = "outdated"
    CONFLICT = "conflict"
    REPEATED_KNOWLEDGE = "repeated_knowledge"


class BenchmarkCase(BaseModel):
    """不可变基准样例；模型字段禁止重新赋值，可变容器由调用方视为只读，深冻结留给存储层复制/序列化。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="1.0", min_length=1)
    case_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    category: CaseCategory
    annotation_reason: str = Field(min_length=1)
    required_claims: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)
    allowed_source_ids: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)
    answer_key: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)
    local_knowledge_ids: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    need_research: bool

    @model_validator(mode="after")
    def validate_research_need(self):
        if self.category is CaseCategory.LOCAL_SUFFICIENT and self.need_research:
            raise ValueError(f"category {self.category.value} cannot need research")
        if self.category in {CaseCategory.LOCAL_PARTIAL, CaseCategory.LOCAL_MISSING,
                             CaseCategory.OUTDATED, CaseCategory.CONFLICT} and not self.need_research:
            raise ValueError(f"category {self.category.value} requires research")
        return self
