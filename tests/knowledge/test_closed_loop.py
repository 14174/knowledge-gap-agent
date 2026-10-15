import hashlib
import json
from datetime import datetime, timezone

import pytest

from knowledge_gap_agent.runtime.models import EvidenceView, ModelReply
from knowledge_gap_agent.knowledge.sufficiency import assess
from knowledge_gap_agent.knowledge.verification import verify_candidate
from knowledge_gap_agent.knowledge.store import SQLiteKnowledgeProvider


class FixedModel:
    def __init__(self, result):
        self.result = result
        self.payload = None

    def complete(self, system, payload, *, max_tokens=1800):
        self.payload = payload
        return ModelReply(text=json.dumps(self.result), input_tokens=11,
                          output_tokens=7, model="fixed-demo", raw={"fixed": True})


def evidence():
    text = "冻结集合使用元组，序列化为数组。"
    return (EvidenceView(ref_id="e1", text=text, source_id="source",
                         content_hash=hashlib.sha256(text.encode()).hexdigest()),)


def verified(**changes):
    args = dict(text="冻结集合使用元组。", evidence_refs=("e1",), evidence=evidence(),
                model=FixedModel(dict(accepted=True, confidence=0.95, reason="正文支持")),
                allowed_sources=("source",), now=datetime.now(timezone.utc), source_run="run-1")
    args.update(changes)
    return verify_candidate(**args)


def test_store_reopen_and_deduplicate(tmp_path):
    candidate = verified().candidate
    provider = SQLiteKnowledgeProvider(tmp_path / "knowledge.db")
    first = provider.put_verified(candidate)
    assert provider.put_verified(candidate) == first
    assert len(provider.entries()) == 1
    provider.close()
    reopened = SQLiteKnowledgeProvider(tmp_path / "knowledge.db")
    assert reopened.search("元组", top_k=1)[0].knowledge_id == first.knowledge_id
    assert reopened.search("元组")[0].score > 0
    reopened.close()


@pytest.mark.parametrize("field,value", [("text", "伪造正文"), ("source_run", "other"),
                                        ("evidence_refs", ("other",)), ("target_hash", "0" * 64)])
def test_put_rejects_stale_credential(tmp_path, field, value):
    candidate = verified().candidate.model_copy(update={field: value})
    with SQLiteKnowledgeProvider(tmp_path / "k.db") as provider:
        with pytest.raises(ValueError):
            provider.put_verified(candidate)
        assert provider.entries() == ()


def test_put_rejects_replaced_evidence(tmp_path):
    ev = evidence()[0].model_copy(update={"text": "修改后正文"})
    candidate = verified().candidate.model_copy(update={"evidence": (ev,)})
    with SQLiteKnowledgeProvider(tmp_path / "k.db") as provider:
        with pytest.raises(ValueError):
            provider.put_verified(candidate)


@pytest.mark.parametrize("change", [dict(evidence_refs=("missing",)), dict(allowed_sources=()),
                                  dict(text=" "), dict(evidence_refs=("e1", "e1")),
                                  dict(evidence_refs=())])
def test_deterministic_rejections_retained(change):
    result = verified(**change)
    assert not result.accepted and result.candidate is None and result.reason


@pytest.mark.parametrize("accepted,confidence", [(False, .99), (True, .79)])
def test_semantic_rejection(accepted, confidence):
    result = verified(model=FixedModel(dict(accepted=accepted, confidence=confidence, reason="不支持")))
    assert not result.accepted and result.reply.raw == {"fixed": True}


@pytest.mark.parametrize("label,missing,stale,conflict", [
    ("enough", (), (), ()), ("missing", ("缺少说明",), (), ()),
    ("partial", (), (), ("e1",)), ("partial", (), ("e1",), ())])
def test_assess_only_question_and_evidence(label, missing, stale, conflict):
    model = FixedModel(dict(label=label, missing_claims=missing, stale_ids=stale,
                           conflict_ids=conflict, confidence=.9, reason="判断理由"))
    decision = assess("为什么用元组？", evidence(), model)
    assert decision.needs_research == (label != "enough")
    assert set(model.payload) == {"question", "evidence"}
    assert decision.reply.input_tokens == 11


@pytest.mark.parametrize("updates", [dict(stale_ids=["unseen"]), dict(missing_claims=["缺口"]),
                                    dict(conflict_ids=["e1"])])
def test_assess_rejects_invalid_combinations(updates):
    result = dict(label="enough", missing_claims=[], stale_ids=[], conflict_ids=[], confidence=.9, reason="判断")
    result.update(updates)
    decision = assess("问题", evidence(), FixedModel(result))
    assert decision.needs_research and "无效" in decision.reason
    assert "unseen" not in decision.stale_ids + decision.conflict_ids


def test_low_confidence_triggers_research():
    result = dict(label="enough", missing_claims=[], stale_ids=[], conflict_ids=[], confidence=.79, reason="不确定")
    assert assess("问题", evidence(), FixedModel(result)).needs_research


def test_review_bool_is_strict():
    result = verified(model=FixedModel(dict(accepted="false", confidence=.99, reason="非法布尔值")))
    assert not result.accepted and "无效" in result.reason


def test_put_rejects_review_swapping(tmp_path):
    candidate = verified().candidate
    changed = candidate.model_copy(update={"review": candidate.review.model_copy(update={"confidence": .1})})
    with SQLiteKnowledgeProvider(tmp_path / "k.db") as provider:
        with pytest.raises(ValueError): provider.put_verified(changed)


def test_put_rejects_raw_boolean(tmp_path):
    with SQLiteKnowledgeProvider(tmp_path / "k.db") as provider:
        with pytest.raises((ValueError, TypeError)): provider.put_verified(True)


@pytest.mark.parametrize("top_k", [0, -1, True, 1.5])
def test_search_validates_top_k(tmp_path, top_k):
    with SQLiteKnowledgeProvider(tmp_path / "k.db") as provider:
        with pytest.raises((ValueError, TypeError)): provider.search("元组", top_k)


def test_stable_id_independent_of_temporary_reference_and_run(tmp_path):
    first = verified().candidate
    ev = evidence()[0].model_copy(update={"ref_id": "new-ref"})
    second = verified(evidence=(ev,), evidence_refs=("new-ref",), source_run="run-2").candidate
    with SQLiteKnowledgeProvider(tmp_path / "k.db") as provider:
        assert provider.put_verified(first) == provider.put_verified(second)
        assert len(provider.entries()) == 1


def test_deterministic_rejection_keeps_target_for_audit():
    result = verified(evidence_refs=("outside",))
    assert result.request["text"] == "冻结集合使用元组。"
    assert result.request["evidence_refs"] == ["outside"]


def test_stable_id_preserves_source_hash_correspondence(tmp_path):
    def views(swapped):
        texts = ("甲证据正文", "乙证据正文")
        if swapped:
            texts = texts[::-1]
        return tuple(EvidenceView(ref_id=f"e{index}", text=text, source_id=source,
                                 content_hash=hashlib.sha256(text.encode()).hexdigest())
                     for index, (source, text) in enumerate(zip(("s1", "s2"), texts)))

    first = verified(evidence=views(False), evidence_refs=("e0", "e1"),
                     allowed_sources=("s1", "s2")).candidate
    second = verified(evidence=views(True), evidence_refs=("e0", "e1"),
                      allowed_sources=("s1", "s2")).candidate
    with SQLiteKnowledgeProvider(tmp_path / "k.db") as provider:
        left = provider.put_verified(first)
        right = provider.put_verified(second)
        assert left.knowledge_id != right.knowledge_id
        assert len(provider.entries()) == 2


def test_multisource_reuse_cannot_drop_source_admission(tmp_path):
    text = "另一来源补充说明。"
    other = EvidenceView(ref_id="other", text=text, source_id="second",
                         content_hash=hashlib.sha256(text.encode()).hexdigest())
    first = verified(evidence=evidence() + (other,), evidence_refs=("e1", "other"),
                     allowed_sources=("source", "second")).candidate
    with SQLiteKnowledgeProvider(tmp_path / "k.db") as provider:
        view = provider.put_verified(first).as_evidence()
        reused = verified(evidence=(view,), evidence_refs=(view.ref_id,),
                          allowed_sources=(view.source_id,))
        assert not reused.accepted and "来源" in reused.reason
        assert view.source_ids == ("second", "source")
        accepted = verified(evidence=(view,), evidence_refs=(view.ref_id,),
                            allowed_sources=("source", "second"))
        assert accepted.accepted
        assert accepted.request["evidence"][0]["source_ids"] == ["second", "source"]


@pytest.mark.parametrize("source_ids", [("source", "source"), (" ",), ("other",)])
def test_multisource_view_rejects_invalid_identity(source_ids):
    with pytest.raises(ValueError):
        EvidenceView.model_validate({**evidence()[0].model_dump(), "source_ids": source_ids})


def test_multisource_identity_expands_all_sources(tmp_path):
    base = evidence()[0]
    multisource = base.model_copy(update={"source_ids": ("source", "additional")})
    first = verified().candidate
    second = verified(evidence=(multisource,), allowed_sources=("source", "additional")).candidate
    with SQLiteKnowledgeProvider(tmp_path / "k.db") as provider:
        one = provider.put_verified(first)
        two = provider.put_verified(second)
        assert two.source_ids == ("additional", "source")
        assert one.knowledge_id != two.knowledge_id
