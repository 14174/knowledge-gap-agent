import json
from pathlib import Path

import pytest

from knowledge_gap_agent.eval.dataset import load_candidate_dataset
from knowledge_gap_agent.eval.io import write_once
from knowledge_gap_agent.eval.report import build_report, save_report
from knowledge_gap_agent.eval.runner import initialize_batch
from knowledge_gap_agent.eval.reuse import freeze_reuse_questions
from knowledge_gap_agent.eval.skills import freeze_candidate, prepare_skill_state
from test_grading_runner import make_config

ROOT = Path(__file__).resolve().parents[2]


def test_offline_report_keeps_registered_failure_denominator(tmp_path):
    dataset = load_candidate_dataset(ROOT)
    initialize_batch(dataset, tmp_path, make_config(), repeats=3)
    report = build_report(tmp_path)
    assert report["variants"]["e2"]["expected_runs"] == 96
    assert report["variants"]["e2"]["task_success"] == 0
    assert report["variants"]["e2"]["missing_runs"] == 96
    assert report["paired"]["e2_minus_e0"]["available"] is False
    save_report(tmp_path)
    assert (tmp_path / "report.json").exists()
    assert "待真人终审" in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_offline_report_closes_budget_database(tmp_path, monkeypatch):
    import sqlite3
    from knowledge_gap_agent.eval.ledger import CallLedger

    dataset = load_candidate_dataset(ROOT)
    initialize_batch(dataset, tmp_path, make_config(), repeats=1)
    CallLedger(tmp_path / "calls.sqlite", limit=2)
    connection = sqlite3.connect(tmp_path / "calls.sqlite")
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: connection)
    build_report(tmp_path)
    try:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    finally:
        connection.close()


def test_reuse_manifest_has_eight_distinct_questions(tmp_path):
    dataset = load_candidate_dataset(ROOT)
    manifest = freeze_reuse_questions(dataset, tmp_path)
    assert len(manifest["groups"]) == 8
    for group in manifest["groups"]:
        assert group["round_two_question"] != dataset.by_id(group["case_id"]).case.question
    assert freeze_reuse_questions(dataset, tmp_path) == manifest


def test_candidate_cannot_be_frozen_without_real_development_traces(tmp_path):
    with pytest.raises(ValueError, match="开发轨迹"):
        freeze_candidate(tmp_path, None, repeats=3)


def test_skill_preparation_is_frozen_unavailable_without_development(tmp_path):
    dataset = load_candidate_dataset(ROOT)
    initialize_batch(dataset, tmp_path, make_config(), repeats=1)
    state = prepare_skill_state(dataset, make_config(), tmp_path, lambda _: None, repeats=1)
    assert state["status"] == "unavailable"
    assert (tmp_path / "skill/preparation.json").exists()
    assert prepare_skill_state(dataset, make_config(), tmp_path, lambda _: None, repeats=1) == state


def test_candidate_preparation_rejects_first_creation_after_holdout(tmp_path):
    dataset = load_candidate_dataset(ROOT)
    initialize_batch(dataset, tmp_path, make_config(), repeats=1)
    write_once(tmp_path / "runs/main/existing/result.json", {"already": "observed"})
    with pytest.raises(ValueError, match="留出"):
        prepare_skill_state(dataset, make_config(), tmp_path, lambda _: None, repeats=1)
