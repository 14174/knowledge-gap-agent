import json
from pathlib import Path

import pytest

from knowledge_gap_agent.eval.dataset import load_candidate_dataset, snapshot_dataset
from knowledge_gap_agent.eval.ledger import BudgetExceeded, CallLedger
from knowledge_gap_agent.eval.metrics import confusion_metrics, paired_bootstrap, summarize

ROOT = Path(__file__).resolve().parents[2]


def test_dataset_hides_labels_and_excluded_pool(tmp_path):
    dataset = load_candidate_dataset(ROOT)
    assert len(dataset.evaluation_cases) == 32
    assert len(dataset.development_cases) == 16
    case = dataset.evaluation_cases[0]
    task, tool = dataset.prepare(case.case_id)
    assert set(task.model_dump()) == {"question", "knowledge"}
    assert not {"claim_ids", "required_claims", "category"} & set(task.model_dump())
    tool(task.question)
    assert set(tool.ref_map.values()) <= set(case.environment.visible_chunk_ids + case.environment.research_chunk_ids)
    assert not set(tool.ref_map.values()) & set(case.environment.excluded_chunk_ids)
    snapshot_dataset(dataset, tmp_path)
    assert (tmp_path / "runtime/tasks.jsonl").exists()
    assert (tmp_path / "labels/cases.jsonl").exists()
    assert (tmp_path / "audit/metadata.json").exists()
    assert "answer_key" not in (tmp_path / "runtime/tasks.jsonl").read_text(encoding="utf-8")


def test_budget_persists_attempts_and_resume(tmp_path):
    path = tmp_path / "calls.sqlite"
    ledger = CallLedger(path, limit=2)
    ledger.reserve("first")
    CallLedger(path, limit=2).reserve("timeout")
    with pytest.raises(BudgetExceeded):
        ledger.reserve("third")
    assert ledger.used == 2


def test_budget_atomic_under_parallel_workers(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    ledger = CallLedger(tmp_path / "concurrent.sqlite", limit=9)
    def reserve(_):
        try:
            ledger.reserve("并发")
            return True
        except BudgetExceeded:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve, range(20))) == 9
    assert ledger.used == 9


def test_metrics_hand_calculated_and_zero_denominator():
    result = confusion_metrics(tp=7, fp=4, tn=6, fn=3)
    assert result["precision"] == 7 / 11
    assert result["recall"] == 0.7
    assert result["false_sufficient_rate"] == 0.3
    assert confusion_metrics(tp=0, fp=0, tn=0, fn=0)["f1"] is None
    assert summarize([{"success": True}, {"success": False}], expected_count=4)["task_success"] == 0.25


def test_bootstrap_is_clustered_and_rejects_missing_pairs():
    expected = [(f"case-{topic}-{env}", topic, repeat) for topic in (5, 6) for env in range(4) for repeat in range(3)]
    left = { (case, repeat): 0.0 for case, _, repeat in expected }
    right = { key: 1.0 for key in left }
    result = paired_bootstrap(left, right, expected)
    assert result["mean_difference"] == result["lower"] == result["upper"] == 1.0
    del right[next(iter(right))]
    assert paired_bootstrap(left, right, expected)["available"] is False
