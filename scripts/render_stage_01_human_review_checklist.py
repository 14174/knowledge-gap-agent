from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from knowledge_gap_agent.benchmark.models import KnowledgeEnvironment
from knowledge_gap_agent.benchmark.review import (
    HumanReviewQueueRecord,
    ReviewInput,
    ReviewRecord,
    build_review_input,
)
from knowledge_gap_agent.contracts.benchmark import BenchmarkCase
from knowledge_gap_agent.corpus.models import Claim, CorpusChunk
from knowledge_gap_agent.utils.canonical import canonical_json


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_INPUTS = (
    "drafts.jsonl",
    "human_review_queue.jsonl",
    "review_inputs.jsonl",
    "reviews.jsonl",
)
CORPUS_INPUTS = ("chunks.jsonl", "claims.jsonl")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} 必须是 JSON 对象")
        rows.append(value)
    return rows


def _index_models(rows: list[Any], key: str, label: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for row in rows:
        value = row
        for part in key.split("."):
            value = getattr(value, part)
        if value in result:
            raise ValueError(f"{label} 存在重复 {key}: {value}")
        result[value] = row
    return result


def _load_inputs(root: Path) -> tuple[
    dict[str, BenchmarkCase],
    dict[str, KnowledgeEnvironment],
    dict[str, HumanReviewQueueRecord],
    dict[str, ReviewInput],
    dict[str, ReviewRecord],
    dict[str, CorpusChunk],
    dict[str, Claim],
]:
    benchmark = root / "fixtures" / "benchmark"
    corpus = root / "fixtures" / "corpus"
    paths = [benchmark / name for name in BENCHMARK_INPUTS]
    paths.extend(corpus / name for name in CORPUS_INPUTS)
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"缺少渲染输入: {missing}")

    cases: list[BenchmarkCase] = []
    environments_by_case: dict[str, KnowledgeEnvironment] = {}
    seen_environment_ids: set[str] = set()
    for envelope in _load_jsonl(benchmark / "drafts.jsonl"):
        if set(envelope) != {"case", "environment"}:
            raise ValueError("draft envelope 必须且只能包含 case 和 environment")
        case = BenchmarkCase.model_validate(envelope["case"])
        environment = KnowledgeEnvironment.model_validate(envelope["environment"])
        if case.case_id in environments_by_case:
            raise ValueError(f"drafts 存在重复 case_id: {case.case_id}")
        if environment.environment_id in seen_environment_ids:
            raise ValueError(f"drafts 存在重复 environment_id: {environment.environment_id}")
        if case.environment_id != environment.environment_id:
            raise ValueError(f"case 与 environment 不匹配: {case.case_id}")
        cases.append(case)
        environments_by_case[case.case_id] = environment
        seen_environment_ids.add(environment.environment_id)

    drafts = _index_models(cases, "case_id", "drafts")
    queue = _index_models(
        [
            HumanReviewQueueRecord.model_validate(row)
            for row in _load_jsonl(benchmark / "human_review_queue.jsonl")
        ],
        "case_id",
        "human review queue",
    )
    review_inputs = _index_models(
        [
            ReviewInput.model_validate(row)
            for row in _load_jsonl(benchmark / "review_inputs.jsonl")
        ],
        "case.case_id",
        "review inputs",
    )
    reviews = _index_models(
        [ReviewRecord.model_validate(row) for row in _load_jsonl(benchmark / "reviews.jsonl")],
        "case_id",
        "reviews",
    )
    chunks = _index_models(
        [CorpusChunk.model_validate(row) for row in _load_jsonl(corpus / "chunks.jsonl")],
        "chunk_id",
        "chunks",
    )
    claims = _index_models(
        [Claim.model_validate(row) for row in _load_jsonl(corpus / "claims.jsonl")],
        "claim_id",
        "claims",
    )
    return drafts, environments_by_case, queue, review_inputs, reviews, chunks, claims


def _validate_case_sets(
    drafts: dict[str, BenchmarkCase],
    environments: dict[str, KnowledgeEnvironment],
    queue: dict[str, HumanReviewQueueRecord],
    review_inputs: dict[str, ReviewInput],
    reviews: dict[str, ReviewRecord],
    chunks: dict[str, CorpusChunk],
    claims: dict[str, Claim],
) -> None:
    full_ids = set(drafts)
    if len(full_ids) != 48:
        raise ValueError(f"当前阶段必须有 48 条 draft，实际为 {len(full_ids)}")
    if set(review_inputs) != full_ids or set(reviews) != full_ids:
        raise ValueError("draft、review input、review 的 case 集合必须精确一致")

    pending_ids = {
        case_id
        for case_id, case in drafts.items()
        if case.human_review_status.value == "pending"
    }
    if len(queue) != 24:
        raise ValueError(f"人工队列必须有 24 条，实际为 {len(queue)}")
    if set(queue) != pending_ids:
        raise ValueError("人工队列必须精确等于 draft 中 pending 的 case 集合")
    distribution = Counter(row.category.value for row in queue.values())
    if distribution != {"outdated": 12, "conflict": 12}:
        raise ValueError(f"人工队列类别必须为 12 outdated + 12 conflict，实际为 {dict(distribution)}")

    for case_id in sorted(full_ids):
        draft = drafts[case_id]
        rebuilt = build_review_input(
            draft,
            environments[case_id],
            chunks.values(),
            claims.values(),
        )
        if rebuilt.model_dump(mode="json") != review_inputs[case_id].model_dump(mode="json"):
            raise ValueError(f"归档 review input 与当前 draft/environment/corpus 不一致: {case_id}")
        review = reviews[case_id]
        if review.review_target_hash != rebuilt.review_target_hash:
            raise ValueError(f"review_target_hash 不一致: {case_id}")

    for case_id, queued in queue.items():
        draft = drafts[case_id]
        review_input = review_inputs[case_id]
        review = reviews[case_id]
        expected_queue = HumanReviewQueueRecord(
            case_id=case_id,
            category=draft.category,
            review_target_hash=review_input.review_target_hash,
            trigger="high_risk_category",
            decision=review.decision,
            reviewer_confidence=review.reviewer_confidence,
            prompt_version=review.prompt_version,
        )
        if queued.model_dump(mode="json") != expected_queue.model_dump(mode="json"):
            raise ValueError(f"人工队列记录与当前 draft/input/review 不一致: {case_id}")


def build_cards(root: Path) -> tuple[
    list[tuple[str, dict[str, Any]]],
    dict[str, CorpusChunk],
    dict[str, Claim],
]:
    drafts, environments, queue, review_inputs, reviews, chunks, claims = _load_inputs(root)
    _validate_case_sets(
        drafts,
        environments,
        queue,
        review_inputs,
        reviews,
        chunks,
        claims,
    )

    cards: list[tuple[str, dict[str, Any]]] = []
    for case_id in queue:
        queued = queue[case_id]
        item = review_inputs[case_id]
        case = item.case.model_dump(mode="json")
        environment = item.environment.model_dump(mode="json")
        draft = drafts[case_id].model_dump(mode="json")
        card = {
            "case_id": case_id,
            "base_question_id": case["base_question_id"],
            "category": case["category"],
            "trigger": queued.trigger,
            "review_target_hash": item.review_target_hash,
            "environment_hash": environment["environment_hash"],
            "visible_chunk_ids": [row["chunk_id"] for row in environment["visible_chunks"]],
            "research_chunk_ids": [row["chunk_id"] for row in environment["research_chunks"]],
            "excluded_chunk_ids": [row["chunk_id"] for row in environment["excluded_chunks"]],
            "question": case["question"],
            "answer_key": case["answer_key"],
            "required_claim_ids": case["required_claim_ids"],
            "required_claims": case["required_claims"],
            "evidence_chunk_ids": case["evidence_chunk_ids"],
            "missing_claim_ids": case["missing_claim_ids"],
            "draft_status": draft["draft_status"],
            "review_status": draft["review_status"],
            "human_review_status": draft["human_review_status"],
            "model_review": reviews[case_id].model_dump(mode="json"),
            "human_decision": None,
            "human_reason": None,
            "requested_changes": [],
        }
        cards.append((case_id, card))
    cards.sort(
        key=lambda item: (
            item[1]["base_question_id"],
            item[1]["category"],
            item[0],
        )
    )
    return cards, chunks, claims


def build_evidence_directory(
    cards: list[tuple[str, dict[str, Any]]],
    chunks: dict[str, CorpusChunk],
    claims: dict[str, Claim],
) -> list[tuple[str, dict[str, Any]]]:
    referenced = {
        chunk_id
        for _, card in cards
        for field in ("visible_chunk_ids", "research_chunk_ids", "excluded_chunk_ids")
        for chunk_id in card[field]
    }
    missing_chunks = sorted(referenced - chunks.keys())
    if missing_chunks:
        raise ValueError(f"缺少被卡片引用的 chunk: {missing_chunks}")

    evidence: list[tuple[str, dict[str, Any]]] = []
    for chunk_id in sorted(referenced):
        chunk = chunks[chunk_id]
        missing_claims = [claim_id for claim_id in chunk.claim_ids if claim_id not in claims]
        if missing_claims:
            raise ValueError(f"chunk {chunk_id} 缺少 claim: {missing_claims}")
        evidence.append(
            (
                chunk_id,
                {
                    **chunk.model_dump(mode="json"),
                    "claims": [
                        claims[claim_id].model_dump(mode="json")
                        for claim_id in chunk.claim_ids
                    ],
                },
            )
        )
    return evidence


def render_markdown(
    cards: list[tuple[str, dict[str, Any]]],
    evidence: list[tuple[str, dict[str, Any]]],
) -> str:
    lines = [
        "# 阶段一人工终审清单",
        "",
        "## 当前门禁",
        "",
        "本清单由固定夹具确定性生成，共 24 张高风险卡片：12 条 `outdated` 与 12 条 `conflict`。",
        "模型 `approve` 不等于人工批准；所有人工字段当前均为空，清单本身也不是冻结输入。",
        "在真实人工结论生成并通过可信记录校验前，当前禁止正式 freeze 和创建阶段标签。",
        "",
        "## 审核方法",
        "",
        "逐卡核对问题、答案键、必需主张、三池编号、目标哈希和完整模型复核记录。",
        "证据正文统一放在后面的去重证据目录；按三池编号查阅，不在卡片中重复正文。",
        "人工审核完成后应另行生成绑定当前 `review_target_hash` 的 `HumanReviewRecord`；不要直接修改本文件中的空字段。",
        "",
        "## 审核卡片",
        "",
    ]
    for case_id, card in cards:
        lines.extend(
            [
                f"### {card['base_question_id']} / {card['category']} / {case_id}",
                "",
                f"<!-- review-card:{case_id} -->",
                "```json",
                canonical_json(card),
                "```",
                "",
            ]
        )

    lines.extend(
        [
            "## 去重证据目录",
            "",
            "以下目录覆盖全部卡片三池引用的 chunk 并按 `chunk_id` 排序；每个 chunk 只出现一次。",
            "",
        ]
    )
    for chunk_id, item in evidence:
        lines.extend(
            [
                f"### {chunk_id}",
                "",
                f"<!-- evidence-chunk:{chunk_id} -->",
                "```json",
                canonical_json(item),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def render(root: Path) -> str:
    cards, chunks, claims = build_cards(root)
    evidence = build_evidence_directory(cards, chunks, claims)
    return render_markdown(cards, evidence)


def write_output_atomic(output: Path, content: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, output)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="确定性渲染阶段一人工终审清单")
    parser.add_argument("--workspace-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--output", type=Path, default=Path("docs/阶段一人工终审清单.md"))
    args = parser.parse_args()

    workspace_root = args.workspace_root.resolve()
    output = args.output if args.output.is_absolute() else workspace_root / args.output
    content = render(workspace_root)
    write_output_atomic(output, content)


if __name__ == "__main__":
    main()
