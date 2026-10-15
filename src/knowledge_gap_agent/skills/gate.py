from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from knowledge_gap_agent.knowledge.verification import digest
from knowledge_gap_agent.runtime.models import FrozenModel


class CandidateSkill(FrozenModel):
    scope: str = Field(min_length=1)
    steps: tuple[str, ...]
    source_runs: tuple[str, ...]
    development_task_ids: tuple[str, ...]
    version: str = Field(min_length=1)

    @model_validator(mode="after")
    def nonempty(self):
        for values in (self.steps, self.source_runs, self.development_task_ids):
            if not values or any(not v.strip() for v in values) or len(set(values)) != len(values):
                raise ValueError("候选来源、步骤与开发任务必须非空且唯一")
        if not self.scope.strip() or not self.version.strip():
            raise ValueError("适用范围与版本不能为空")
        return self

    @property
    def content_hash(self) -> str:
        return digest(self.model_dump(mode="json"))


class ScorePair(FrozenModel):
    task_id: str = Field(min_length=1)
    split: Literal["target", "regression"]
    baseline_score: float = Field(ge=0, le=1)
    candidate_score: float = Field(ge=0, le=1)
    baseline_cost: float = Field(ge=0)
    candidate_cost: float = Field(ge=0)
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("task_id")
    @classmethod
    def nonblank_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("配对任务编号不能为空白")
        return value


class EvaluationManifest(FrozenModel):
    frozen_path: str
    candidate_hash: str
    development_task_ids: tuple[str, ...]
    target_task_ids: tuple[str, ...]
    regression_task_ids: tuple[str, ...]
    max_regression: float = Field(ge=0, le=1)
    manifest_hash: str


def _manifest(candidate: CandidateSkill, target_ids: tuple[str, ...], regression_ids: tuple[str, ...],
              max_regression: float, path: str | Path) -> EvaluationManifest:
    candidate = CandidateSkill.model_validate(candidate.model_dump())
    groups = (candidate.development_task_ids, tuple(target_ids), tuple(regression_ids))
    if any(not g or len(set(g)) != len(g) or any(not s.strip() for s in g) for g in groups):
        raise ValueError("分集必须非空且任务唯一")
    if any(set(groups[a]) & set(groups[b]) for a, b in ((0, 1), (0, 2), (1, 2))):
        raise ValueError("开发与留出分集不得交叉")
    values = dict(candidate_hash=candidate.content_hash,
                  development_task_ids=tuple(sorted(groups[0])),
                  target_task_ids=tuple(sorted(groups[1])), regression_task_ids=tuple(sorted(groups[2])),
                  max_regression=max_regression)
    return EvaluationManifest(**values, manifest_hash=digest(values), frozen_path=str(Path(path).resolve()))


def freeze_evaluation(candidate: CandidateSkill, target_task_ids: tuple[str, ...],
                      regression_task_ids: tuple[str, ...], path: str | Path,
                      *, max_regression: float = 0.0) -> EvaluationManifest:
    manifest = _manifest(candidate, target_task_ids, regression_task_ids, max_regression, path)
    path = Path(path)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(manifest.model_dump_json() + "\n")
    except FileExistsError:
        if EvaluationManifest.model_validate_json(path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("冻结清单已存在，禁止同轮修改") from None
    return manifest


class SkillGateResult(FrozenModel):
    status: Literal["validated", "rejected"]
    reasons: tuple[str, ...]
    candidate_hash: str
    manifest_hash: str
    target_delta: float | None = None
    regression_rate: float | None = None
    cost_delta: float | None = None


def evaluate_skill(candidate: CandidateSkill, target_pairs: tuple[ScorePair, ...],
                   regression_pairs: tuple[ScorePair, ...], *, manifest: EvaluationManifest,
                   max_regression: float = 0.0,
                   manifest_path: str | Path | None = None) -> SkillGateResult:
    reasons = []
    try:
        candidate = CandidateSkill.model_validate(candidate.model_dump())
        manifest = EvaluationManifest.model_validate(manifest.model_dump())
        actual_path = Path(manifest_path) if manifest_path is not None else Path(manifest.frozen_path)
        expected = _manifest(candidate, manifest.target_task_ids, manifest.regression_task_ids, max_regression,
                             actual_path)
        # 原机器位置是审计元数据，不是候选与分集的内容身份。
        if manifest.model_dump(exclude={"frozen_path"}) != expected.model_dump(exclude={"frozen_path"}):
            raise ValueError("候选或冻结清单不匹配")
        disk = EvaluationManifest.model_validate_json(actual_path.read_text(encoding="utf-8"))
        if disk != manifest:
            raise ValueError("磁盘冻结清单发生变化")
        groups = (tuple(ScorePair.model_validate(p.model_dump()) for p in target_pairs),
                  tuple(ScorePair.model_validate(p.model_dump()) for p in regression_pairs))
        for pairs, ids, split in zip(groups,
                (manifest.target_task_ids, manifest.regression_task_ids), ("target", "regression")):
            if (not pairs or len({p.task_id for p in pairs}) != len(pairs)
                    or {p.task_id for p in pairs} != set(ids)):
                raise ValueError("配对任务缺失、重复或与冻结集合不符")
            if any(p.split != split or p.candidate_hash != candidate.content_hash for p in pairs):
                raise ValueError("配对分集或候选版本不符")
    except (ValueError, OSError) as exc:
        return SkillGateResult(status="rejected", reasons=(str(exc),),
            candidate_hash=candidate.content_hash, manifest_hash=manifest.manifest_hash)
    targets, regressions = groups
    target_delta = sum(p.candidate_score-p.baseline_score for p in targets) / len(targets)
    regression_rate = sum(p.candidate_score < p.baseline_score for p in regressions) / len(regressions)
    all_pairs = targets + regressions
    cost_delta = sum(p.candidate_cost-p.baseline_cost for p in all_pairs) / len(all_pairs)
    if target_delta < 0:
        reasons.append("目标集平均得分下降")
    if regression_rate > max_regression:
        reasons.append("回归任务下降比例超阈值")
    return SkillGateResult(status="rejected" if reasons else "validated", reasons=tuple(reasons),
        candidate_hash=candidate.content_hash, manifest_hash=manifest.manifest_hash,
        target_delta=target_delta, regression_rate=regression_rate, cost_delta=cost_delta)
