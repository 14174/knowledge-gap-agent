from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from knowledge_gap_agent.knowledge.store import KnowledgeEntry, SQLiteKnowledgeProvider
from knowledge_gap_agent.utils.canonical import sha256_hex
from .io import read_json, write_once
from .runner import execute_case, grade_case, run_name


ROUND_TWO_QUESTIONS = {
    5: "实现语料处理、检索排序、基准管理和执行循环时，各自应该负责什么？如何避免相同能力出现多份实现？",
    6: "请说明一个智能体消息接口怎样区分发送角色，以及多轮消息怎样形成下一次模型调用的上下文。",
    7: "短期任务状态和跨任务的语义知识应该如何区分职责？它们分别适合怎样保留和存储？",
    8: "请串起从异构文档统一成Markdown、切块和向量化、存储检索，到把证据放进提示词并生成答案的RAG流程，并解释统一格式的作用。",
    9: "如果要同时评价知识不足识别和智能体整体表现，为什么单一分数不够？应分别观察哪些方面？",
    10: "设计可审计数据发布流程时，执行输入、评测答案和审核记录应怎样分开？发布前如何证明必要的真人审核已经发生？",
    11: "学习智能体工程时，如何安排从小型可运行项目到评测和轨迹观测的练习顺序？",
    12: "请列出候选数据需要升级人工复核的情况，并解释即使自动评估通过为什么仍需最终人工质量检查。",
}


def freeze_reuse_questions(dataset, output):
    groups = [{"topic": case.topic, "case_id": case.case_id,
               "round_one_question": case.case.question,
               "round_two_question": ROUND_TWO_QUESTIONS[case.topic],
               "audit": "按原问题同一知识范围预写相关问题；不读取答案键，不新增答案提示；两轮问题不同。"}
              for case in dataset.evaluation_cases if case.case.category.value == "local_partial"]
    if len(groups) != 8 or any(g["round_one_question"] == g["round_two_question"] for g in groups):
        raise ValueError("复用清单应有八组不同问题")
    manifest = {"groups": groups, "manifest_hash": sha256_hex(groups)}
    write_once(Path(output) / "reuse_manifest.json", manifest)
    return manifest


def run_reuse(dataset, config, output, client_factory, *, repeats=3, workers=4):
    output = Path(output)
    from .skills import prepare_skill_state
    prepare_skill_state(dataset, config, output, client_factory, repeats=repeats)
    manifest = freeze_reuse_questions(dataset, output)

    def group_run(job):
        group, repeat = job
        case_id = group["case_id"]
        # 主实验该题E3已真实研究写回时直接使用，避免额外模型调用且保留来源运行。
        main_path = output / "runs/main" / run_name(case_id, "e3", repeat) / "result.json"
        first = read_json(main_path) if main_path.exists() else execute_case(
            dataset, case_id, "e3", repeat, config, output, client_factory, phase="reuse_first")
        added = set((first.get("writeback") or {}).get("added_ids", []))
        database = output / "runs" / first["phase"] / run_name(case_id, "e3", repeat) / "knowledge.sqlite"
        if not database.exists():
            raise FileNotFoundError("第一轮实际知识库不存在，不能用JSON模拟检索")
        with SQLiteKnowledgeProvider(database) as provider:
            entries = provider.entries()
            if [entry.model_dump(mode="json") for entry in entries] != first["knowledge_entries"]:
                raise ValueError("第一轮知识库与已保存写回记录不一致")
            hits = provider.search(group["round_two_question"], top_k=4)
        # 读取实际SQLite并调用真实Provider检索，只传入同组新增且真实命中的知识。
        # 无写回臂从相同初始可见池构造，既不读新增条目也不沿用第一轮答案。
        new_entries = tuple(entry for entry in hits if entry.knowledge_id in added)
        records = []
        for arm, extra in (("reuse_without_write", ()), ("reuse_with_write", new_entries)):
            record = execute_case(dataset, case_id, "e2", repeat, config, output, client_factory,
                                  phase=arm, question=group["round_two_question"], extra_entries=extra)
            records.append(record)
        with_write = records[1]
        observed_refs = {view["ref_id"] for view in (with_write.get("result") or {}).get("task", {}).get("knowledge", [])}
        citations = set((with_write.get("result") or {}).get("citations", []))
        audit = {"case_id": case_id, "repeat": repeat, "added_ids": sorted(added),
                 "provider_hit_ids": [entry.knowledge_id for entry in new_entries],
                 "retrieved_new_ids": sorted(added & observed_refs),
                 "reused_ids": sorted(added & observed_refs & citations),
                 "first_error": first["error_type"], "first_run_id": (first.get("result") or {}).get("run_id")}
        write_once(output / "reuse" / f"{case_id}__{repeat}.json", audit)
        return first, *records

    jobs = [(group, repeat) for repeat in range(1, repeats + 1) for group in manifest["groups"]]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        groups = list(pool.map(group_run, jobs))
    # 运行优先，评分后置；所有原始回答均先写盘。
    all_records = [record for group in groups for record in group]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda record: grade_case(dataset, record, config, output, client_factory), all_records))
    return all_records
