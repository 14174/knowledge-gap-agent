"""固定数据工程演示：回归拒绝，通过仅代表验证，不晋升策略。"""
from pathlib import Path
from tempfile import TemporaryDirectory

from knowledge_gap_agent.skills.gate import CandidateSkill, ScorePair, evaluate_skill, freeze_evaluation


def main():
    print("固定数据工程演示，不进入效果报告；通过不自动晋升")
    candidate = CandidateSkill(scope="证据回答", steps=("核对引用",), source_runs=("demo-dev-run",),
                              development_task_ids=("dev",), version="1")
    with TemporaryDirectory() as folder:
        manifest = freeze_evaluation(candidate, ("target",), ("regression",), Path(folder) / "freeze.json")
        target = (ScorePair(task_id="target", split="target", baseline_score=.5, candidate_score=.7,
            baseline_cost=1, candidate_cost=1, candidate_hash=candidate.content_hash),)
        for score in (.4, .5):
            regression = (ScorePair(task_id="regression", split="regression", baseline_score=.5,
                candidate_score=score, baseline_cost=1, candidate_cost=1, candidate_hash=candidate.content_hash),)
            result = evaluate_skill(candidate, target, regression, manifest=manifest)
            assert result.status == ("rejected" if score < .5 else "validated")
            print(result.model_dump_json())


if __name__ == "__main__":
    main()
