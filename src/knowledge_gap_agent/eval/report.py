from pathlib import Path
from contextlib import closing

from .io import read_json, read_jsonl, write_once
from .metrics import divide, paired_bootstrap, summarize
from .skills import evaluate_saved_skill


def build_report(output):
    output = Path(output)
    from .integrity import validate_protocol, validate_run, validate_grade
    protocol = validate_protocol(output)
    labels = {row["case_id"]: row for row in read_jsonl(output / "snapshot/labels/cases.jsonl")}
    rows = []
    registered = {(case_id, variant, repeat) for case_id in protocol["evaluation"]
                  for variant in protocol["variants"] for repeat in range(1, protocol["repeats"] + 1)}
    seen = set()
    for path in sorted((output / "runs/main").glob("*/result.json")):
        run = validate_run(read_json(path), output)
        case_id, variant, repeat = run["key"]
        key = (case_id, variant, repeat)
        if key not in registered or key in seen:
            raise ValueError("结果身份不属于预注册集合或发生重复")
        seen.add(key)
        grade_path = path.with_name("grade.json")
        grade = validate_grade(read_json(grade_path), run) if grade_path.exists() else {"success": False, "grade_missing": True, "usage": {}}
        decision = run.get("decision")
        prediction = None
        if decision:
            prediction = decision["label"] != "enough" or decision["confidence"] < .8 or bool(decision["stale_ids"] or decision["conflict_ids"] or decision["missing_claims"])
        elif run.get("result") and run["result"]["stop_reason"] == "answered":
            prediction = run["search_calls"] > 0
        result = run.get("result") or {}
        semantic = grade.get("grade") or {}
        supports = semantic.get("citation_support", {})
        row = {"case_id": case_id, "variant": variant, "repeat": repeat,
               "topic": labels[case_id]["topic"], "success": grade["success"] and not run["error_type"],
               "grade_missing": grade["grade_missing"], "need_research": labels[case_id]["need_research"],
               "predicted_research": prediction, "executed_research": run["search_calls"] > 0,
               "search_calls": run["search_calls"], "runtime_input_tokens": run["usage"]["input_tokens"],
               "runtime_output_tokens": run["usage"]["output_tokens"], "runtime_latency_ms": run["runtime_latency_ms"],
               "steps": len(result.get("calls", [])), "judge_input_tokens": grade["usage"].get("input_tokens"),
               "judge_output_tokens": grade["usage"].get("output_tokens"),
               "judge_latency_ms": grade["usage"].get("model_latency_ms"),
               "citation_count": len(result.get("citations", [])),
               "supported_citations": sum(supports.values()),
               "scored_citations": len(supports), "all_citations_legal": grade.get("all_citations_legal", False)}
        rows.append(row)
    expected_count = len(protocol["evaluation"]) * protocol["repeats"]
    variants = {variant: summarize([row for row in rows if row["variant"] == variant], expected_count=expected_count)
                for variant in protocol["variants"]}
    from .metrics import confusion_metrics
    for variant, summary in variants.items():
        selected = [row for row in rows if row["variant"] == variant]
        summary["citation_support_rate"] = divide(sum(r["supported_citations"] for r in selected), sum(r["scored_citations"] for r in selected))
        summary["citation_present_rate"] = divide(sum(r["citation_count"] > 0 for r in selected), expected_count)
        summary["legal_citation_run_rate"] = divide(sum(r["all_citations_legal"] for r in selected), expected_count)
        summary["execution_confusion"] = confusion_metrics(
            tp=sum(r["executed_research"] and r["need_research"] for r in selected),
            fp=sum(r["executed_research"] and not r["need_research"] for r in selected),
            tn=sum(not r["executed_research"] and not r["need_research"] for r in selected),
            fn=sum(not r["executed_research"] and r["need_research"] for r in selected))
    expected = [(case_id, protocol["topics"][case_id], repeat) for case_id in protocol["evaluation"]
                for repeat in range(1, protocol["repeats"] + 1)]
    paired = {}
    for baseline in ("e0", "e1"):
        left = {(r["case_id"], r["repeat"]): float(r["success"]) for r in rows if r["variant"] == baseline and not r["grade_missing"]}
        right = {(r["case_id"], r["repeat"]): float(r["success"]) for r in rows if r["variant"] == "e2" and not r["grade_missing"]}
        paired[f"e2_minus_{baseline}"] = paired_bootstrap(left, right, expected)
        for metric in ("search_calls", "runtime_input_tokens", "runtime_latency_ms"):
            a = {(r["case_id"], r["repeat"]): r[metric] for r in rows if r["variant"] == baseline and r[metric] is not None}
            b = {(r["case_id"], r["repeat"]): r[metric] for r in rows if r["variant"] == "e2" and r[metric] is not None}
            paired[f"e2_minus_{baseline}_{metric}"] = paired_bootstrap(a, b, expected)
    reuse = _reuse_report(output, protocol)
    skill = evaluate_saved_skill(output) if (output / "skill/evaluation_manifest.json").exists() else {"status": "未运行"}
    ledger_path = output / "calls.sqlite"
    attempts = None
    if ledger_path.exists():
        import sqlite3
        with closing(sqlite3.connect(ledger_path)) as connection:
            attempts = connection.execute("SELECT count(*) FROM attempts").fetchone()[0]
    # 所有已保存调用，包括中断后重跑的尝试；不把调用级未知用量算零。
    calls = [read_json(path) for path in output.rglob("call-*.json")]
    runtime_calls = [call for call in calls if call["component"] != "judge"]
    judge_calls = [call for call in calls if call["component"] == "judge"]
    from .recording import total_usage
    components = sorted({call["component"] for call in calls})
    recorded_attempts = sum(len(call.get("attempts", [])) for call in calls)
    return {"status": "候选数据探索结果，二十四条待真人终审；不是正式性能结论", "protocol": protocol,
            "variants": variants, "paired": paired, "reuse": reuse, "skill": skill, "rows": rows,
            "http_attempts_reserved": attempts, "runtime_all_saved_usage": total_usage(runtime_calls),
            "http_attempts_recorded": recorded_attempts,
            "reserved_without_recorded_attempt": max(0, attempts - recorded_attempts) if attempts is not None else None,
            "judge_all_saved_usage": total_usage(judge_calls),
            "component_usage": {component: total_usage([call for call in calls if call["component"] == component]) for component in components},
            "limits": ["四十八环境源自十二个主题，留出只有八个主题簇", "三次重复不是独立主题扩容", "单模型裁判可能存在系统偏差", "人工终审改变标签或正文后需要重跑"]}


def _reuse_report(output, protocol):
    from .integrity import validate_run, validate_grade
    expected = 8 * protocol["repeats"]
    audits = [read_json(path) for path in (output / "reuse").glob("*.json")]
    searches = {"reuse_with_write": 0, "reuse_without_write": 0}
    quality = {arm: 0 for arm in searches}
    complete = True
    for audit in audits:
        from .runner import run_name
        name = run_name(audit["case_id"], "e2", audit["repeat"])
        for arm in searches:
            path = output / "runs" / arm / name / "result.json"
            if not path.exists():
                complete = False
                continue
            run = read_json(path)
            if run["key"] != [audit["case_id"], "e2", audit["repeat"]] or run["phase"] != arm:
                raise ValueError("复用运行身份与配对审计不一致")
            validate_run(run, output)
            searches[arm] += run["search_calls"]
            grade = path.with_name("grade.json")
            quality[arm] += bool(validate_grade(read_json(grade), run)["success"]) if grade.exists() else False
    return {"expected_pairs": expected, "observed_pairs": len(audits),
            "retrieval_hit_rate": divide(sum(bool(a["retrieved_new_ids"]) for a in audits), expected),
            "actual_citation_reuse_rate": divide(sum(bool(a["reused_ids"]) for a in audits), expected),
            "search_calls": searches, "quality": {arm: divide(value, expected) for arm, value in quality.items()},
            "repeated_search_reduction": 1 - searches["reuse_with_write"] / searches["reuse_without_write"]
                if complete and len(audits) == expected and searches["reuse_without_write"] else None}


def markdown_report(report):
    lines = ["# 首轮探索实验报告", "", report["status"], "", "| 变体 | 预注册 | 已运行 | 保守成功率 | 评分缺失 | 平均搜索 |", "|---|---:|---:|---:|---:|---:|"]
    for name, row in report["variants"].items():
        lines.append(f"| {name} | {row['expected_runs']} | {row['observed_runs']} | {row['task_success']} | {row['grading_missing']} | {row['mean_search_calls']} |")
    lines += ["", "## 配对统计", "", "按主题簇进行一千次自助采样；缺失配对不提供区间。", ""]
    for name, value in report["paired"].items():
        lines.append(f"- {name}：{value}")
    lines += ["", "## 知识复用", "", str(report["reuse"]), "", "## 候选技能", "", str(report["skill"]), "", "## 限制", ""]
    lines += ["- " + value for value in report["limits"]]
    lines += ["", "报告仅从已保存产物重算，不发起模型或搜索请求。", ""]
    return "\n".join(lines)


def save_report(output, destination=None):
    output = Path(output)
    destination = Path(destination) if destination else output
    destination.mkdir(parents=True, exist_ok=True)
    report = build_report(output)
    write_once(destination / "report.json", report)
    path = destination / "report.md"
    content = markdown_report(report)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise FileExistsError("报告已经存在不同内容，请使用新报告目录")
    if not path.exists():
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    return report
