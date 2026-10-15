from dataclasses import replace
from pathlib import Path

import pytest

from knowledge_gap_agent.eval.dataset import load_candidate_dataset
from knowledge_gap_agent.eval.io import read_json, write_once
from knowledge_gap_agent.eval.report import build_report
from knowledge_gap_agent.eval.runner import execute_case, grade_case, initialize_batch
from test_grading_runner import FixedClient, make_config

ROOT = Path(__file__).resolve().parents[2]


def test_snapshot_byte_change_is_rejected(tmp_path):
    dataset = load_candidate_dataset(ROOT)
    initialize_batch(dataset, tmp_path, make_config(), repeats=1)
    path = tmp_path / "snapshot/labels/cases.jsonl"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="摘要"):
        build_report(tmp_path)


def test_complete_raw_runs_without_grades_do_not_make_success_interval(tmp_path):
    dataset = load_candidate_dataset(ROOT)
    dataset = replace(dataset, cases=(dataset.evaluation_cases[0],))
    initialize_batch(dataset, tmp_path, make_config(), repeats=1)
    case_id = dataset.evaluation_cases[0].case_id
    for variant in ("e0", "e2"):
        execute_case(dataset, case_id, variant, 1, make_config(), tmp_path, FixedClient)
    report = build_report(tmp_path)
    assert report["variants"]["e2"]["task_success"] == 0
    assert report["paired"]["e2_minus_e0"]["available"] is False


def test_grade_rejects_same_identity_but_changed_answer(tmp_path):
    dataset = load_candidate_dataset(ROOT)
    initialize_batch(dataset, tmp_path, make_config(), repeats=1)
    run = execute_case(dataset, dataset.evaluation_cases[0].case_id, "e2", 1, make_config(), tmp_path, FixedClient)
    grade_case(dataset, run, make_config(), tmp_path, FixedClient)
    changed = {**run, "result": {**run["result"], "answer": "另一份回答"}}
    with pytest.raises(ValueError, match="摘要|评分|轨迹"):
        grade_case(dataset, changed, make_config(), tmp_path, FixedClient)


def test_sidecar_detects_grade_identity_tamper(tmp_path):
    path = tmp_path / "grade.json"
    write_once(path, {"key": ["case", "e2", 1]})
    path.write_text('{"key":["other","e2",1]}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="摘要"):
        read_json(path)


def test_reuse_report_rejects_run_bound_to_other_case(tmp_path):
    from knowledge_gap_agent.eval.report import _reuse_report
    from knowledge_gap_agent.eval.runner import run_name
    write_once(tmp_path / "reuse/pair.json", {
        "case_id": "expected", "repeat": 1, "retrieved_new_ids": [], "reused_ids": []})
    for arm in ("reuse_with_write", "reuse_without_write"):
        write_once(tmp_path / "runs" / arm / run_name("expected", "e2", 1) / "result.json", {
            "key": ["other", "e2", 1], "phase": arm,
            "identity": {"key": ["other", "e2", 1], "phase": arm}, "search_calls": 1})
    with pytest.raises(ValueError, match="复用.*身份"):
        _reuse_report(tmp_path, {"repeats": 1})
