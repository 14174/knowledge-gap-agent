import pytest

from knowledge_gap_agent.skills.gate import CandidateSkill, ScorePair, freeze_evaluation, evaluate_skill


def candidate():
    return CandidateSkill(scope="回答前核对证据", steps=("检索", "检查引用"), source_runs=("run",),
                          development_task_ids=("dev-01",), version="1")


def pair(c, task="target", split="target", baseline=.5, score=.8):
    return ScorePair(task_id=task, split=split, baseline_score=baseline, candidate_score=score,
                     baseline_cost=1, candidate_cost=2, candidate_hash=c.content_hash)


def evaluate(c, target, regression, tmp_path):
    manifest = freeze_evaluation(c, ("target",), ("regression",), tmp_path / "freeze.json")
    return evaluate_skill(c, target, regression, manifest=manifest)


def test_validated_is_not_promoted(tmp_path):
    c = candidate()
    result = evaluate(c, (pair(c),), (pair(c, "regression", "regression"),), tmp_path)
    assert result.status == "validated" and result.cost_delta == 1
    assert (tmp_path / "freeze.json").exists()


@pytest.mark.parametrize("baseline,score", [(.9, .8), (.5, .4)])
def test_rejects_regression(tmp_path, baseline, score):
    c = candidate()
    result = evaluate(c, (pair(c),), (pair(c, "regression", "regression", baseline, score),), tmp_path)
    assert result.status == "rejected" and result.reasons


@pytest.mark.parametrize("kind", ["empty", "duplicate", "wrong_hash", "wrong_split", "overlap", "target_loss"])
def test_rejects_bad_pairs(tmp_path, kind):
    c = candidate()
    target = (pair(c),)
    regression = (pair(c, "regression", "regression"),)
    if kind == "empty": target = ()
    if kind == "duplicate": target = target * 2
    if kind == "wrong_hash": target = (target[0].model_copy(update={"candidate_hash": "0" * 64}),)
    if kind == "wrong_split": target = (target[0].model_copy(update={"split": "regression"}),)
    if kind == "overlap": regression = (pair(c, "target", "regression"),)
    if kind == "target_loss": target = (pair(c, score=.4),)
    assert evaluate(c, target, regression, tmp_path).status == "rejected"


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -.1, 1.1])
def test_finite_bounded_scores(score):
    with pytest.raises(ValueError): pair(candidate(), score=score)


def test_development_holdout_isolation(tmp_path):
    c = candidate()
    with pytest.raises(ValueError):
        freeze_evaluation(c, ("dev-01",), ("regression",), tmp_path / "freeze.json")


def test_manifest_cannot_be_replaced(tmp_path):
    c = candidate()
    freeze_evaluation(c, ("target",), ("regression",), tmp_path / "freeze.json")
    with pytest.raises(ValueError):
        freeze_evaluation(c, ("changed",), ("regression",), tmp_path / "freeze.json")


def test_gate_rejects_changed_disk_manifest(tmp_path):
    c = candidate()
    manifest = freeze_evaluation(c, ("target",), ("regression",), tmp_path / "freeze.json")
    (tmp_path / "freeze.json").write_text("{}", encoding="utf-8")
    result = evaluate_skill(c, (pair(c),), (pair(c, "regression", "regression"),), manifest=manifest)
    assert result.status == "rejected"


def test_nondefault_threshold_is_frozen(tmp_path):
    c = candidate()
    manifest = freeze_evaluation(c, ("target",), ("regression",), tmp_path / "freeze.json", max_regression=1)
    args = (c, (pair(c),), (pair(c, "regression", "regression", score=.4),))
    assert evaluate_skill(*args, manifest=manifest, max_regression=1).status == "validated"
    assert evaluate_skill(*args, manifest=manifest, max_regression=0).status == "rejected"


def test_new_candidate_version_rejected_by_old_manifest(tmp_path):
    c = candidate()
    manifest = freeze_evaluation(c, ("target",), ("regression",), tmp_path / "freeze.json")
    changed = c.model_copy(update={"version": "2"})
    assert evaluate_skill(changed, (pair(changed),), (pair(changed, "regression", "regression"),),
                          manifest=manifest).status == "rejected"


def test_whitespace_pair_identity_rejected():
    with pytest.raises(ValueError):
        pair(candidate(), task=" ")
