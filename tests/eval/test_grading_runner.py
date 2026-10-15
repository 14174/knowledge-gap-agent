import hashlib
import json
from pathlib import Path

from knowledge_gap_agent.contracts.config import RunConfig
from knowledge_gap_agent.runtime.models import ModelReply
from knowledge_gap_agent.eval.dataset import load_candidate_dataset
from knowledge_gap_agent.eval.grading import grade_answer
from knowledge_gap_agent.eval.runner import execute_case, initialize_batch
from knowledge_gap_agent.eval.recording import RecordedClient
from knowledge_gap_agent.tracing.store import replay_run

ROOT = Path(__file__).resolve().parents[2]


class FixedClient:
    def __init__(self, config):
        self.config = config
        self.payloads = []
    def complete(self, system, payload, **kwargs):
        self.payloads.append(payload)
        if "逐要点" in system:
            text = json.dumps({"covered": [True] * len(payload["answer_key"]), "critical_error": False,
                               "citation_support": {ref: True for ref in payload["evidence"]}, "reason": "证据支持"})
        elif "判断充分性" in system:
            text = json.dumps({"label": "enough", "confidence": .9, "reason": "证据完整"})
        elif not payload["observations"] and "必须先研究" in system:
            text = json.dumps({"kind": "research", "query": payload["question"]})
        else:
            evidence = payload["knowledge"] or payload["observations"][0]["evidence"]
            text = json.dumps({"kind": "answer", "answer": "依据材料作答", "citations": [evidence[0]["ref_id"]]})
        return ModelReply(text=text, input_tokens=5, output_tokens=3, model="fixed", raw={"usage": {"input_tokens":5,"output_tokens":3}})


def make_config(variant="e2"):
    return RunConfig(experiment_id="test", variant=variant, model_provider="fixed", model_name="fixed",
                     model_revision="fixed", temperature=0, max_steps=3, timeout_seconds=5,
                     retry_limit=0, prompt_hash="0"*64, toolset_version="test", dataset_version="test",
                     corpus_hash="0"*64, random_seed=1)


def test_runner_uses_real_loop_preserves_identity_and_resumes(tmp_path):
    dataset = load_candidate_dataset(ROOT)
    config = make_config()
    initialize_batch(dataset, tmp_path, config, repeats=1)
    case = dataset.evaluation_cases[0]
    clients = []
    def factory(c):
        client = FixedClient(c)
        clients.append(client)
        return client
    result = execute_case(dataset, case.case_id, "e2", 1, config, tmp_path, factory)
    assert result["key"] == [case.case_id, "e2", 1]
    assert result["result"]["stop_reason"] == "answered"
    assert result["search_calls"] == 0
    assert replay_run(tmp_path / result["trace_path"]).answer == result["result"]["answer"]
    assert not any("answer_key" in payload or "required_claims" in payload for client in clients for payload in client.payloads)
    count = len(clients)
    assert execute_case(dataset, case.case_id, "e2", 1, config, tmp_path, factory) == result
    assert len(clients) == count


def test_grader_rejects_missing_or_unknown_citations(tmp_path):
    model = FixedClient(make_config())
    result = grade_answer(question="问题", answer_key=["要点"], answer="答案", citations=["bad"], evidence={}, model=model)
    assert result["success"] is False
    assert result["all_citations_legal"] is False
    assert model.payloads == []


def test_enough_gate_hard_blocks_unexpected_research(tmp_path):
    class Disobedient(FixedClient):
        def complete(self, system, payload, **kwargs):
            if "判断充分性" in system:
                return super().complete(system, payload, **kwargs)
            self.payloads.append(payload)
            return ModelReply(text=json.dumps({"kind": "research", "query": "强行搜索"}),
                              input_tokens=2, output_tokens=2, model="fixed", raw={})
    dataset = load_candidate_dataset(ROOT)
    record = execute_case(dataset, dataset.evaluation_cases[0].case_id, "e2", 1,
                          make_config(), tmp_path, Disobedient)
    assert record["search_calls"] == 0
    assert record["error_type"] == "research_forbidden_by_gate"
    assert record["policy_violation"] is True
    assert "只能作答" in record["result"]["system_prompt"]


def test_recording_persists_failure_and_unknown_usage(tmp_path):
    class Broken(FixedClient):
        def complete(self, *args, **kwargs):
            raise TimeoutError()
    client = RecordedClient(Broken(make_config()), tmp_path)
    try:
        client.complete("系统", {})
    except TimeoutError:
        pass
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert client.records[0]["input_tokens"] is None
