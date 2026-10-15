import json
from pathlib import Path

from knowledge_gap_agent.skills.gate import CandidateSkill, ScorePair, EvaluationManifest, evaluate_skill, freeze_evaluation
from .io import read_json, write_once
from .recording import RecordedClient, total_usage
from .runner import execute_case, grade_case, run_name


DISTILL_PROMPT = "只根据这些开发任务真实轨迹提炼一个可复用执行策略。不得写问题答案。仅输出JSON：scope(适用条件文字),steps(简洁步骤数组)。"


def pair_id(case_id, repeat):
    return f"{case_id}__{repeat}"


def freeze_candidate(output, client, *, repeats=3):
    output = Path(output)
    candidate_path = output / "skill/candidate.json"
    if candidate_path.exists():
        return CandidateSkill.model_validate(read_json(candidate_path))
    if _has_holdout(output):
        raise ValueError("留出运行已开始，禁止事后提炼候选")
    traces = [read_json(path) for path in sorted((output / "runs/smoke").glob("*/result.json"))]
    traces = [record for record in traces if record.get("result") and record["result"]["calls"]]
    if not traces:
        raise ValueError("缺少真实开发轨迹，不能提炼候选")
    protocol = read_json(output / "protocol.json")
    allowed = set(protocol["development"])
    if any(record["key"][0] not in allowed for record in traces):
        raise ValueError("候选来源包含留出主题")
    model = RecordedClient(client, output / "skill/distill_calls")
    model.component = "skill_distill"
    # 提炼输入不包含开发评分或留出结果，只给实际运行轨迹。
    selected = traces[:8]
    reply = model.complete(DISTILL_PROMPT, {"traces": [
        {"question": record["result"]["task"]["question"], "stop_reason": record["result"]["stop_reason"],
         "actions": [event["arguments"] for event in record["result"]["events"] if event["event_type"] == "action_selected"],
         "observations": record["result"]["observations"]} for record in selected]})
    data = json.loads(reply.text)
    if set(data) != {"scope", "steps"}:
        raise ValueError("技能提炼输出结构无效")
    candidate = CandidateSkill(scope=data["scope"], steps=tuple(data["steps"]),
                source_runs=tuple(record["result"]["run_id"] for record in selected),
                development_task_ids=tuple(sorted({record["key"][0] for record in selected})), version="candidate-v1")
    write_once(candidate_path, candidate.model_dump(mode="json"))
    write_once(output / "skill/distill_usage.json", total_usage(model.records))
    return candidate


def _has_holdout(output):
    return any(path.is_file() for phase in ("main", "reuse_first", "reuse_with_write", "reuse_without_write", "skill")
               for path in (Path(output) / "runs" / phase).rglob("*"))


def prepare_skill_state(dataset, config, output, client_factory, *, repeats=3):
    """留出前固化候选或不可用结论；不可用不会在看到留出后补提炼。"""
    output = Path(output)
    path = output / "skill/preparation.json"
    if path.exists():
        state = read_json(path)
        if state["repeats"] != repeats:
            raise ValueError("预冻结技能重复次数冲突")
        if state["status"] == "ready":
            candidate = CandidateSkill.model_validate(read_json(output / "skill/candidate.json"))
            manifest = EvaluationManifest.model_validate(read_json(output / "skill/evaluation_manifest.json"))
            if candidate.content_hash != state["candidate_hash"] or manifest.manifest_hash != state["manifest_hash"]:
                raise ValueError("候选或分集偏离预冻结状态")
        return state
    if _has_holdout(output):
        raise ValueError("留出运行已存在，不能事后建立候选冻结状态")
    target_ids = tuple(pair_id(case.case_id, r) for case in dataset.evaluation_cases if case.topic >= 9 for r in range(1, repeats + 1))
    regression_ids = tuple(pair_id(case.case_id, r) for case in dataset.evaluation_cases if case.topic <= 8 for r in range(1, repeats + 1))
    try:
        candidate = freeze_candidate(output, client_factory(config), repeats=repeats)
        manifest = freeze_evaluation(candidate, target_ids, regression_ids, output / "skill/evaluation_manifest.json")
        # 技能模块独占创建清单；评测读取入口额外固定原始文件摘要。
        from .io import _seal
        _seal(output / "skill/evaluation_manifest.json")
        state = {"status": "ready", "candidate_hash": candidate.content_hash,
                 "manifest_hash": manifest.manifest_hash, "repeats": repeats}
    except Exception as exc:
        state = {"status": "unavailable", "reason": type(exc).__name__, "repeats": repeats,
                 "target_task_ids": list(target_ids), "regression_task_ids": list(regression_ids)}
        write_once(output / "skill/unavailable.json", state)
    write_once(path, state)
    return state


def run_skill(dataset, config, output, client_factory, *, repeats=3, workers=4):
    from concurrent.futures import ThreadPoolExecutor
    output = Path(output)
    state_path = output / "skill/preparation.json"
    if not state_path.exists():
        raise ValueError("技能评测只消费留出前预冻结候选，请先执行prepare")
    state = read_json(state_path)
    if state["status"] != "ready":
        return {"status": "unavailable", "reason": "留出前未获得有效候选"}
    candidate = CandidateSkill.model_validate(read_json(output / "skill/candidate.json"))
    manifest = EvaluationManifest.model_validate(read_json(output / "skill/evaluation_manifest.json"))
    if candidate.content_hash != state["candidate_hash"] or manifest.manifest_hash != state["manifest_hash"]:
        raise ValueError("技能评测候选偏离预冻结版本")
    prompt = "\n可选候选策略，仅在适用时采用：" + candidate.scope + "；" + "；".join(candidate.steps)
    jobs = [(case.case_id, repeat) for case in dataset.evaluation_cases for repeat in range(1, repeats + 1)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        records = list(pool.map(lambda job: execute_case(dataset, job[0], "e2", job[1], config, output,
                    client_factory, phase="skill", candidate_prompt=prompt), jobs))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda record: grade_case(dataset, record, config, output, client_factory), records))
    return evaluate_saved_skill(output)


def evaluate_saved_skill(output):
    output = Path(output)
    from .integrity import validate_protocol, validate_run, validate_grade
    validate_protocol(output)
    candidate = CandidateSkill.model_validate(read_json(output / "skill/candidate.json"))
    manifest = EvaluationManifest.model_validate(read_json(output / "skill/evaluation_manifest.json"))
    target, regression = [], []
    missing = []
    for split, ids in (("target", manifest.target_task_ids), ("regression", manifest.regression_task_ids)):
        for identity in ids:
            case_id, repeat_text = identity.rsplit("__", 1)
            name = run_name(case_id, "e2", int(repeat_text))
            paths = [output / "runs" / phase / name / file for phase in ("main", "skill") for file in ("result.json", "grade.json")]
            if not all(path.exists() for path in paths):
                missing.append(identity)
                continue
            baseline, baseline_grade, candidate_run, candidate_grade = [read_json(path) for path in paths]
            expected_key = [case_id, "e2", int(repeat_text)]
            if (baseline["key"] != expected_key or baseline["phase"] != "main"
                    or candidate_run["key"] != expected_key or candidate_run["phase"] != "skill"):
                raise ValueError("技能配对运行身份与冻结清单不一致")
            validate_run(baseline, output)
            validate_run(candidate_run, output)
            validate_grade(baseline_grade, baseline)
            validate_grade(candidate_grade, candidate_run)
            costs = [run["usage"]["input_tokens"] + run["usage"]["output_tokens"]
                     if run["usage"]["input_tokens"] is not None and run["usage"]["output_tokens"] is not None else None
                     for run in (baseline, candidate_run)]
            if any(value is None for value in costs) or baseline_grade["grade_missing"] or candidate_grade["grade_missing"]:
                missing.append(identity)
                continue
            pair = ScorePair(task_id=identity, split=split, baseline_score=float(baseline_grade["success"]),
                     candidate_score=float(candidate_grade["success"]), baseline_cost=costs[0], candidate_cost=costs[1],
                     candidate_hash=candidate.content_hash)
            (target if split == "target" else regression).append(pair)
    gate = evaluate_skill(candidate, tuple(target), tuple(regression), manifest=manifest,
                          manifest_path=output / "skill/evaluation_manifest.json")
    value = {"gate": gate.model_dump(mode="json"), "missing_pairs": missing,
             "target_pairs": [p.model_dump(mode="json") for p in target],
             "regression_pairs": [p.model_dump(mode="json") for p in regression],
             "status": "offline_candidate_only_no_promotion"}
    # 每次完整重算返回；历史评审结果由调用方另存新目录。
    return value
