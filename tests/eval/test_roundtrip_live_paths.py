"""固定模型只检验真实工程路径，不形成性能数字。"""
import json
from pathlib import Path

import pytest

from knowledge_gap_agent.eval.dataset import load_candidate_dataset
from knowledge_gap_agent.eval.io import read_json
from knowledge_gap_agent.eval.reuse import run_reuse
from knowledge_gap_agent.eval.runner import execute_case, initialize_batch
from knowledge_gap_agent.eval.runner import run_main, grade_phase
from knowledge_gap_agent.eval.skills import run_skill, prepare_skill_state
from knowledge_gap_agent.eval.skills import evaluate_saved_skill
from knowledge_gap_agent.eval.io import write_once
from knowledge_gap_agent.runtime.models import ModelReply
from test_grading_runner import FixedClient, make_config

ROOT = Path(__file__).resolve().parents[2]


class RoundTripClient(FixedClient):
    def complete(self, system, payload, **kwargs):
        if "判断充分性" in system:
            refs = [e["ref_id"] for e in payload["evidence"]]
            label = "enough" if any(ref.startswith("knowledge-") for ref in refs) else "partial"
            data = {"label": label, "confidence": .95, "reason": "固定回归响应"}
        elif "提取一条可复用事实" in system:
            evidence = payload["evidence"][0]
            data = {"text": evidence["text"], "evidence_refs": [evidence["ref_id"]]}
        elif "独立证据审核者" in system:
            data = {"accepted": True, "reason": "固定响应支持", "confidence": .95}
        elif "提炼一个可复用执行策略" in system:
            data = {"scope": "证据问答", "steps": ["检查引文后回答"]}
        else:
            return super().complete(system, payload, **kwargs)
        self.payloads.append(payload)
        return ModelReply(text=json.dumps(data), input_tokens=5, output_tokens=3, model="fixed",
                          raw={"usage": {"input_tokens": 5, "output_tokens": 3}})


def test_e3_extracts_verifies_writes_and_reuse_is_topic_isolated(tmp_path):
    dataset = load_candidate_dataset(ROOT)
    config = make_config("e3")
    initialize_batch(dataset, tmp_path, config, repeats=1)
    records = run_reuse(dataset, config, tmp_path, RoundTripClient, repeats=1, workers=4)
    assert len(records) == 24
    first_round = [record for record in records if record["phase"] == "reuse_first"]
    assert len(first_round) == 8
    assert all(record["writeback"]["status"] == "accepted" for record in first_round)
    assert all(len(record["knowledge_entries"]) == 1 for record in first_round)
    assert len(list((tmp_path / "reuse").glob("*.json"))) == 8
    for record in records:
        if record["phase"] == "reuse_with_write":
            assert len(record["identity"]["extra_ids"]) == 1
        elif record["phase"] == "reuse_without_write":
            assert record["identity"]["extra_ids"] == []


def test_candidate_is_distilled_from_development_then_runs_real_paired_gate(tmp_path):
    dataset = load_candidate_dataset(ROOT)
    config = make_config()
    initialize_batch(dataset, tmp_path, config, repeats=1)
    run_main(dataset, config, tmp_path, RoundTripClient, repeats=1, workers=4, development=True)
    prepare_skill_state(dataset, config, tmp_path, RoundTripClient, repeats=1)
    # 只有E2作为实际无技能基线；不需要复制其余三变体。
    for case in dataset.evaluation_cases:
        execute_case(dataset, case.case_id, "e2", 1, config, tmp_path, RoundTripClient)
    grade_phase(dataset, config, tmp_path, RoundTripClient, workers=4)
    gate = run_skill(dataset, config, tmp_path, RoundTripClient, repeats=1, workers=4)
    assert gate["gate"]["status"] == "validated"
    assert len(gate["target_pairs"]) == len(gate["regression_pairs"]) == 16
    manifest = read_json(tmp_path / "skill/evaluation_manifest.json")
    assert manifest["candidate_hash"] == gate["gate"]["candidate_hash"]


def test_skill_report_rejects_baseline_files_misplaced_as_candidate(tmp_path):
    from dataclasses import replace
    from knowledge_gap_agent.eval.runner import run_name

    dataset = load_candidate_dataset(ROOT)
    dataset = replace(dataset, cases=(dataset.development_cases[0],
        next(case for case in dataset.evaluation_cases if case.topic == 5),
        next(case for case in dataset.evaluation_cases if case.topic == 9)))
    config = make_config()
    initialize_batch(dataset, tmp_path, config, repeats=1)
    run_main(dataset, config, tmp_path, RoundTripClient, repeats=1, development=True)
    prepare_skill_state(dataset, config, tmp_path, RoundTripClient, repeats=1)
    for case in dataset.evaluation_cases:
        execute_case(dataset, case.case_id, "e2", 1, config, tmp_path, RoundTripClient)
    grade_phase(dataset, config, tmp_path, RoundTripClient)
    for case in dataset.evaluation_cases:
        name = run_name(case.case_id, "e2", 1)
        for filename in ("result.json", "grade.json"):
            source = tmp_path / "runs/main" / name / filename
            write_once(tmp_path / "runs/skill" / name / filename, read_json(source))
    with pytest.raises(ValueError, match="技能.*身份"):
        evaluate_saved_skill(tmp_path)
