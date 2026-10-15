from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from knowledge_gap_agent.contracts.config import RunConfig
from knowledge_gap_agent.knowledge.store import SQLiteKnowledgeProvider
from knowledge_gap_agent.knowledge.sufficiency import assess
from knowledge_gap_agent.knowledge.verification import verify_candidate
from knowledge_gap_agent.runtime.loop import DEFAULT_SYSTEM_PROMPT, run_task
from knowledge_gap_agent.runtime.models import TaskInput
from knowledge_gap_agent.utils.canonical import sha256_hex
from .dataset import snapshot_dataset
from .grading import GRADING_PROMPT, grade_answer
from .io import read_json, read_jsonl, write_once
from .recording import RecordedClient, total_usage


FORCE_RESEARCH = "\n你必须先研究，第一步必须输出research动作；观察真实研究结果后再作答。"
ANSWER_ONLY = "\n充分性门禁已判定本地证据充分。你只能作答，必须输出answer动作，不得请求research；研究工具在本分支关闭。"
EXTRACT_PROMPT = "只从本次研究证据提取一条可复用事实，不复制最终答案。仅输出JSON：text(事实正文),evidence_refs(支持它的研究证据ref_id数组)。"


def run_name(case_id, variant, repeat):
    return f"{case_id}__{variant}__{repeat}"


def initialize_batch(dataset, output, config, *, repeats=3, budget=2400):
    output = Path(output)
    if repeats < 1:
        raise ValueError("重复次数必须大于零")
    source_root = Path(__file__).resolve().parents[3]
    code_hashes = {str(path.relative_to(source_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in sorted((source_root / "src/knowledge_gap_agent").rglob("*.py"))}
    protocol = {"schema_version": "1.0", "status": "candidate_exploratory",
                "dataset_hash": dataset.dataset_hash, "base_config": config.model_dump(mode="json"),
                "base_config_hash": config.config_hash, "repeats": repeats,
                "development": [case.case_id for case in dataset.development_cases],
                "evaluation": [case.case_id for case in dataset.evaluation_cases],
                "topics": {case.case_id: case.topic for case in dataset.cases},
                "variants": ["e0", "e1", "e2", "e3"], "threshold": .8,
                "transport_options": {"thinking": {"type": "disabled"}, "max_output_tokens": 1800},
                "top_k": 4, "bootstrap_iterations": 1000, "bootstrap_seed": 20261015,
                "grading_prompt": GRADING_PROMPT, "runtime_prompt": DEFAULT_SYSTEM_PROMPT,
                "force_research_prompt": FORCE_RESEARCH, "extract_prompt": EXTRACT_PROMPT,
                "answer_only_prompt": ANSWER_ONLY,
                "phase_order": ["smoke", "prepare", "main", "grade", "reuse", "skill"],
                "smoke_cases": [case.case_id for case in dataset.development_cases[:2]],
                "http_budget": budget, "max_output_tokens": 1800,
                "code_hashes": code_hashes}
    write_once(output / "protocol.json", protocol)
    snapshot_dataset(dataset, output / "snapshot")
    return protocol


def _writeback(result, client, provider):
    research_evidence = {view.ref_id: view for observation in result.observations for view in observation.evidence}
    if not research_evidence:
        return {"status": "no_research_evidence", "added_ids": []}
    client.component = "extract"
    reply = client.complete(EXTRACT_PROMPT, {"evidence": [e.model_dump(mode="json") for e in research_evidence.values()]})
    data = json.loads(reply.text)
    if set(data) != {"text", "evidence_refs"} or not isinstance(data["text"], str) or not isinstance(data["evidence_refs"], list):
        raise ValueError("知识提取结构无效")
    client.component = "verify"
    verification = verify_candidate(data["text"], tuple(data["evidence_refs"]), tuple(research_evidence.values()), client,
                       allowed_sources=tuple(sorted({e.source_id for e in research_evidence.values()})),
                       now=datetime.now(timezone.utc), source_run=result.run_id)
    added = []
    if verification.accepted:
        before = {entry.knowledge_id for entry in provider.entries()}
        entry = provider.put_verified(verification.candidate)
        if entry.knowledge_id not in before:
            added.append(entry.knowledge_id)
    return {"status": "accepted" if verification.accepted else "rejected",
            "added_ids": added, "verification": verification.model_dump(mode="json")}


def execute_case(dataset, case_id, variant, repeat, base_config, output, client_factory, *,
                 phase="main", question=None, extra_entries=(), candidate_prompt=""):
    output = Path(output)
    directory = output / "runs" / phase / run_name(case_id, variant, repeat)
    result_path = directory / "result.json"
    task, tool = dataset.prepare(case_id, question=question, include_local=variant != "e0")
    # 复用新增知识只能来自显式传入的同组第一轮库。
    extra_views = tuple(entry.as_evidence() for entry in extra_entries)
    if extra_views:
        from knowledge_gap_agent.retrieval.bm25 import BM25Index
        class ViewChunk:
            def __init__(self, view):
                self.chunk_id, self.text = view.ref_id, view.text
        all_views = {e.ref_id: e for e in task.knowledge + extra_views}
        ranked = BM25Index.build(ViewChunk(e) for e in all_views.values()).search(task.question, 4)
        task = TaskInput(question=task.question, knowledge=tuple(all_views[h.chunk_id] for h in ranked))
    system = DEFAULT_SYSTEM_PROMPT + (FORCE_RESEARCH if variant in {"e0", "e1"} else "") + candidate_prompt
    config = RunConfig.model_validate({**base_config.model_dump(mode="json"), "variant": variant,
                "prompt_hash": hashlib.sha256(system.encode("utf-8")).hexdigest(),
                "random_seed": base_config.random_seed + repeat})
    identity = {"key": [case_id, variant, repeat], "phase": phase, "config_hash": config.config_hash,
                "task_hash": sha256_hex(task.model_dump(mode="json")),
                "extra_ids": [entry.knowledge_id for entry in extra_entries]}
    if result_path.exists():
        previous = read_json(result_path)
        if previous["identity"] != identity:
            raise ValueError("恢复运行身份或配置冲突")
        from .integrity import validate_protocol, validate_run
        if (output / "protocol.json").exists():
            validate_protocol(output)
        validate_run(previous, output)
        return previous
    if directory.exists() and any(directory.iterdir()):
        # 中断调用不覆盖；已预留预算不退回。原调用保留在独立尝试目录。
        attempts_root = directory / "interrupted"
        attempts_root.mkdir(exist_ok=True)
        from uuid import uuid4
        archive = attempts_root / str(uuid4())
        archive.mkdir()
        for existing in tuple(directory.iterdir()):
            if existing.name != "interrupted":
                existing.rename(archive / existing.name)
    directory.mkdir(parents=True, exist_ok=True)
    write_once(directory / "identity.json", identity)
    tick = time.monotonic()
    client = RecordedClient(client_factory(config), directory / "calls")
    decision, result, writeback, error = None, None, None, None
    policy = {"violation": False}
    def guarded_research(query):
        if decision is not None and not decision.needs_research:
            policy["violation"] = True
            raise RuntimeError("research_forbidden_by_gate")
        return tool(query)
    with SQLiteKnowledgeProvider(directory / "knowledge.sqlite") as provider:
        try:
            if variant in {"e2", "e3"}:
                client.component = "sufficiency"
                decision = assess(task.question, task.knowledge, client)
                system += FORCE_RESEARCH if decision.needs_research else ANSWER_ONLY
                config = RunConfig.model_validate({**config.model_dump(mode="json"), "prompt_hash": hashlib.sha256(system.encode()).hexdigest()})
                client.config = config
                client.client.config = config
            client.component = "runtime"
            result = run_task(task, config, client, guarded_research, system_prompt=system)
            if policy["violation"]:
                error = "research_forbidden_by_gate"
            if (variant in {"e0", "e1"} or (decision and decision.needs_research)) and not result.observations:
                error = "required_research_not_executed"
            if variant == "e3" and result.stop_reason == "answered" and error is None:
                writeback = _writeback(result, client, provider)
        except Exception as exc:
            error = type(exc).__name__
        entries = [entry.model_dump(mode="json") for entry in provider.entries()]
    views = {view.ref_id: view.model_dump(mode="json") for view in task.knowledge}
    if result:
        views.update({e.ref_id: e.model_dump(mode="json") for obs in result.observations for e in obs.evidence})
    record = {"identity": identity, "key": identity["key"], "phase": phase,
              "result": result.model_dump(mode="json", round_trip=True) if result else None,
              "effective_config": config.model_dump(mode="json"), "effective_config_hash": config.config_hash,
              "decision": decision.model_dump(mode="json") if decision else None,
              "error_type": error, "search_calls": len(tool.queries), "queries": tool.queries,
              "policy_violation": policy["violation"],
              "ref_map": tool.ref_map, "evidence": views, "writeback": writeback,
              "knowledge_entries": entries, "usage": total_usage(client.records),
              "runtime_latency_ms": int((time.monotonic() - tick) * 1000)}
    if result:
        from knowledge_gap_agent.tracing.store import save_run
        trace_path = save_run(result, directory / "trace")
        record["trace_path"] = str(trace_path.relative_to(output))
    write_once(result_path, record)
    return record


def grade_case(dataset, record, base_config, output, client_factory):
    from .integrity import validate_protocol, validate_run, validate_grade
    validate_protocol(output)
    validate_run(record, output)
    directory = Path(output) / "runs" / record["phase"] / run_name(*record["key"])
    path = directory / "grade.json"
    if path.exists():
        cached = read_json(path)
        return validate_grade(cached, record)
    # 原始运行落盘后，评分入口才单独读取物理隔离的答案文件。
    label = next(row for row in read_jsonl(Path(output) / "snapshot/labels/cases.jsonl") if row["case_id"] == record["key"][0])
    runtime_task = next(row["task"] for row in read_jsonl(Path(output) / "snapshot/runtime/tasks.jsonl") if row["case_id"] == record["key"][0])
    client = RecordedClient(client_factory(base_config), directory / "judge_calls")
    client.component = "judge"
    result = record.get("result") or {}
    grade = grade_answer(question=result.get("task", {}).get("question", runtime_task["question"]),
                answer_key=label["answer_key"], answer=result.get("answer") if not record["error_type"] else None,
                citations=result.get("citations", []), evidence=record["evidence"], model=client)
    grade.update(usage=total_usage(client.records), key=record["key"], identity=record["identity"], run_content_hash=sha256_hex(record))
    write_once(path, grade)
    return grade


def run_main(dataset, config, output, client_factory, *, repeats=3, workers=4, development=False):
    if not development:
        from .skills import prepare_skill_state
        prepare_skill_state(dataset, config, output, client_factory, repeats=repeats)
    # 冒烟只跑两个预先固定开发案例；完整开发集合仍在协议中独立保留。
    cases = dataset.development_cases[:2] if development else dataset.evaluation_cases
    jobs = [(case.case_id, variant, repeat) for repeat in range(1, repeats + 1)
            for variant in ("e0", "e1", "e2", "e3") for case in cases]
    phase = "smoke" if development else "main"
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda job: execute_case(dataset, *job, config, output, client_factory, phase=phase), jobs))


def grade_phase(dataset, config, output, client_factory, *, phase="main", workers=4):
    records = [read_json(path) for path in sorted((Path(output) / "runs" / phase).glob("*/result.json"))]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda record: grade_case(dataset, record, config, output, client_factory), records))
