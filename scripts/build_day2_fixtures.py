from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from knowledge_gap_agent.benchmark.models import (
    KnowledgeEnvironment,
    compute_environment_hash,
)
from knowledge_gap_agent.benchmark.validation import validate_dataset
from knowledge_gap_agent.contracts.benchmark import BenchmarkCase, CaseCategory
from knowledge_gap_agent.corpus.chunking import chunk_markdown
from knowledge_gap_agent.corpus.manifest import SourceManifest, SourceManifestEntry
from knowledge_gap_agent.corpus.models import Claim, CorpusChunk, SourceDocument
from knowledge_gap_agent.corpus.normalize import content_hash, normalize_text
from knowledge_gap_agent.retrieval.tokenizer import tokenize
from knowledge_gap_agent.utils.canonical import canonical_json, sha256_hex


ROOT = Path(__file__).resolve().parents[1]
FETCHED_AT = datetime.fromisoformat("2026-09-24T00:00:00+08:00")
OUTDATED_UNTIL = datetime.fromisoformat("2026-09-23T23:59:59+08:00")


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    title: str
    repository: str
    commit_sha: str
    relative_path: str
    local_path: str
    expected_hash: str
    external_directory: str | None = None

    @property
    def source_url(self) -> str:
        return (
            f"https://github.com/{self.repository}/blob/"
            f"{self.commit_sha}/{self.relative_path}"
        )


@dataclass(frozen=True)
class ClaimSeed:
    statement: str
    source_id: str
    needle: str


@dataclass(frozen=True)
class TopicSpec:
    number: int
    name: str
    question: str
    first: ClaimSeed
    second: ClaimSeed


SOURCES = (
    SourceSpec(
        source_id="project-experiment-contract",
        title="知识缺口智能体实验合同",
        repository="14174/knowledge-gap-agent",
        commit_sha="19e13d048cf0e6ba11695f4d6dd954cb8a364ebb",
        relative_path="docs/实验合同.md",
        local_path="fixtures/sources/raw/knowledge-gap-agent/docs/实验合同.md",
        expected_hash="eedddd18ed841e8df3aba21a5568daed3952f060df4a2b4715432cfbf95c77cf",
    ),
    SourceSpec(
        source_id="project-ai-coding-guide",
        title="AI Coding 工程规范",
        repository="14174/knowledge-gap-agent",
        commit_sha="55e1c2f40356558c0cfafcb639830201000af20f",
        relative_path="docs/AI_CODING_GUIDE.md",
        local_path="fixtures/sources/raw/knowledge-gap-agent/docs/AI_CODING_GUIDE.md",
        expected_hash="6e4e4592dbe85587c7984b0d79562657dda97701f1f14037262b6081fc9fe569",
    ),
    SourceSpec(
        source_id="project-decisions",
        title="知识缺口智能体设计决策",
        repository="14174/knowledge-gap-agent",
        commit_sha="55e1c2f40356558c0cfafcb639830201000af20f",
        relative_path="docs/decisions.md",
        local_path="fixtures/sources/raw/knowledge-gap-agent/docs/decisions.md",
        expected_hash="2d182cc774986354fdfc526a0fbc01ff654edcce4851e95b58bfee4297bd2502",
    ),
    SourceSpec(
        source_id="controlled-benchmark-distractors",
        title="受控基准干扰证据",
        repository="14174/knowledge-gap-agent",
        commit_sha="a866aee6b000331ba2fa0e4079b3c8b902e52e20",
        relative_path="fixtures/sources/controlled/benchmark-distractors.md",
        local_path=(
            "fixtures/sources/raw/knowledge-gap-agent/fixtures/sources/controlled/"
            "benchmark-distractors.md"
        ),
        expected_hash="b94b3c1acf993941667dfb37d0033d73c9ce4e59d467680f8eab5fbf97a7ea5d",
    ),
    SourceSpec(
        source_id="agent-learning-hub-readme",
        title="Agent Learning Hub 学习路线",
        repository="datawhalechina/Agent-Learning-Hub",
        commit_sha="dddf777dde6788228136862f270203424a28efbc",
        relative_path="README.md",
        local_path="fixtures/sources/raw/Agent-Learning-Hub/README.md",
        expected_hash="0a2a4329a547a54462ab2f5a13525e8233901588486e57b0afadde18097d20d6",
        external_directory="Agent-Learning-Hub",
    ),
    SourceSpec(
        source_id="hello-agents-chapter-7",
        title="第七章 构建你的 Agent 框架",
        repository="datawhalechina/hello-agents",
        commit_sha="5caceca4e4c9a3d25cd14627881436953f4d6912",
        relative_path="docs/chapter7/第七章 构建你的Agent框架.md",
        local_path=(
            "fixtures/sources/raw/hello-agents/docs/chapter7/"
            "第七章 构建你的Agent框架.md"
        ),
        expected_hash="a6818e1957eb62e6983ab07e381f0a0d73aef13026152aa87bfa97245922b78e",
        external_directory="hello-agents",
    ),
    SourceSpec(
        source_id="hello-agents-chapter-8",
        title="第八章 记忆与检索",
        repository="datawhalechina/hello-agents",
        commit_sha="5caceca4e4c9a3d25cd14627881436953f4d6912",
        relative_path="docs/chapter8/第八章 记忆与检索.md",
        local_path=(
            "fixtures/sources/raw/hello-agents/docs/chapter8/"
            "第八章 记忆与检索.md"
        ),
        expected_hash="97262da77f3ae5fa9745e532bb0fcf14066546775da8644172f40d1a8048dce6",
        external_directory="hello-agents",
    ),
    SourceSpec(
        source_id="hello-agents-chapter-12",
        title="第十二章 智能体性能评估",
        repository="datawhalechina/hello-agents",
        commit_sha="5caceca4e4c9a3d25cd14627881436953f4d6912",
        relative_path="docs/chapter12/第十二章 智能体性能评估.md",
        local_path=(
            "fixtures/sources/raw/hello-agents/docs/chapter12/"
            "第十二章 智能体性能评估.md"
        ),
        expected_hash="4015fad8532c0b8f3406b272d938f1f130c7f11832e1487298055f7b0708e333",
        external_directory="hello-agents",
    ),
)


TOPICS = (
    TopicSpec(
        1,
        "规范 JSON 哈希",
        "如何稳定计算实验配置身份，并明确哪些配置变化必须改变身份哈希？",
        ClaimSeed(
            "规范 JSON 必须按映射键排序、使用 UTF-8，并拒绝非有限数值。",
            "project-ai-coding-guide",
            "映射键排序。",
        ),
        ClaimSeed(
            "会改变实验输入、边界或随机性的冻结变量都必须进入 config_hash。",
            "project-experiment-contract",
            "`random_seed` 均进入 `config_hash`",
        ),
    ),
    TopicSpec(
        2,
        "冻结容器",
        "冻结数据模型怎样避免集合原地修改，并保持 JSON 落盘格式兼容？",
        ClaimSeed(
            "冻结模型的集合字段在 Python 内部使用 tuple，JSON 持久化仍输出数组。",
            "project-decisions",
            "集合字段在 Python 内部使用 `tuple`",
        ),
        ClaimSeed(
            "冻结模型不应使用不可变 list 子类，因为基类方法可绕过覆盖并破坏深复制和 Pickle。",
            "project-ai-coding-guide",
            "不要实现“不可变 `list` 子类”",
        ),
    ),
    TopicSpec(
        3,
        "测试驱动开发",
        "新增行为应按什么测试顺序实现，已发现缺陷应如何长期固定？",
        ClaimSeed(
            "每个新增行为先写目标测试并观察它因功能缺失而失败，再写最小实现。",
            "project-ai-coding-guide",
            "写一个只表达目标行为的测试",
        ),
        ClaimSeed(
            "已发现的实际缺陷应由回归测试固定其复现边界。",
            "project-ai-coding-guide",
            "| 回归测试 | 固定已发现缺陷 |",
        ),
    ),
    TopicSpec(
        4,
        "双级审查",
        "独立任务的规格审查与代码质量审查应如何排序和分工？",
        ClaimSeed(
            "独立任务先做规格审查，通过后再做代码质量审查。",
            "project-ai-coding-guide",
            "每个独立任务按固定顺序审查",
        ),
        ClaimSeed(
            "子任务一次只承担实现、规格审查或质量审查中的一种角色。",
            "project-ai-coding-guide",
            "子任务一次只承担一种角色",
        ),
    ),
    TopicSpec(
        5,
        "模块边界",
        "语料、检索、基准与运行职责应怎样分开，并如何防止实现分叉？",
        ClaimSeed(
            "语料模块负责来源、规范化、切块和证据，不负责检索排名或搜索决策。",
            "project-ai-coding-guide",
            "`src/knowledge_gap_agent/corpus/` | 来源清单",
        ),
        ClaimSeed(
            "新增实现不得复制既有哈希、校验或状态机逻辑，出现重复应先校正上下文。",
            "project-ai-coding-guide",
            "新模块复制了已有哈希、校验或状态机逻辑",
        ),
    ),
    TopicSpec(
        6,
        "Agent 框架消息契约",
        "Agent 框架如何表达角色化消息，并把历史上下文交给模型？",
        ClaimSeed(
            "Message 的 role 被限制为 user、assistant、system、tool 四种标准角色。",
            "hello-agents-chapter-7",
            "将 `role` 字段的取值严格限制",
        ),
        ClaimSeed(
            "Agent 基类用 Message 列表管理历史，具体调用会组合系统、历史与当前用户消息。",
            "hello-agents-chapter-7",
            "添加系统消息（可能包含工具信息）",
        ),
    ),
    TopicSpec(
        7,
        "记忆分层",
        "工作记忆与长期语义记忆分别承担什么职责和存储策略？",
        ClaimSeed(
            "工作记忆面向当前会话的临时信息，容量受限并在会话结束后清理。",
            "hello-agents-chapter-8",
            "容量被有意限制（例如，默认50条）",
        ),
        ClaimSeed(
            "语义记忆保存抽象概念、规则和知识，可结合图数据库与向量数据库。",
            "hello-agents-chapter-8",
            "语义记忆采用了Neo4j图数据库和Qdrant向量数据库的混合架构",
        ),
    ),
    TopicSpec(
        8,
        "检索流程",
        "完整 RAG 流程如何准备知识并将检索结果用于回答？",
        ClaimSeed(
            "RAG 数据准备包含数据提取、文本分割和向量化，应用阶段检索后注入提示词再生成答案。",
            "hello-agents-chapter-8",
            "一个完整的RAG应用流程主要分为两大核心环节",
        ),
        ClaimSeed(
            "异构文档可先转换为 Markdown，再按结构分块、向量化并进入存储检索。",
            "hello-agents-chapter-8",
            "任意格式文档 → MarkItDown转换 → Markdown文本",
        ),
    ),
    TopicSpec(
        9,
        "评测指标",
        "知识缺口实验和通用智能体评测为什么需要多类指标？",
        ClaimSeed(
            "知识缺口实验至少定义任务成功率、Precision、Recall、F1 和错误充分率。",
            "project-experiment-contract",
            "`FalseSufficientRate =",
        ),
        ClaimSeed(
            "不同智能体任务需要不同评估方法，工具调用与问答不能只用同一简单对错标准。",
            "hello-agents-chapter-12",
            "评估标准的多样性",
        ),
    ),
    TopicSpec(
        10,
        "评测数据隔离",
        "运行、标签和审计数据应如何隔离，正式冻结应如何验证人工门禁？",
        ClaimSeed(
            "runtime、labels、audit 必须物理分离，运行载荷按字段白名单构造。",
            "project-ai-coding-guide",
            "运行载荷采用字段白名单构造",
        ),
        ClaimSeed(
            "正式冻结必须重新计算人工门禁，不信任调用方手填的状态字段。",
            "project-ai-coding-guide",
            "正式冻结重新计算门禁",
        ),
    ),
    TopicSpec(
        11,
        "学习路线",
        "Agent 工程学习应如何从可运行作品逐步进入评估与可观测性？",
        ClaimSeed(
            "面向项目的学习者应按 Project Ladder 逐档完成可运行作品。",
            "agent-learning-hub-readme",
            "每一档做一个可运行作品",
        ),
        ClaimSeed(
            "评估阶段应使用固定测试集，并记录成功率、失败原因、工具调用次数、成本和延迟。",
            "agent-learning-hub-readme",
            "为 agent 准备固定测试集",
        ),
    ),
    TopicSpec(
        12,
        "人工门禁",
        "哪些候选基准必须进入人工审核，自动评估为何不能替代最终质量把关？",
        ClaimSeed(
            "过时、冲突、低置信度、被退回或曾规则失败的样本必须进入人工审核。",
            "project-ai-coding-guide",
            "历史规则失败样本必须进入人工审核",
        ),
        ClaimSeed(
            "自动化评估可能遗漏严格推理或主观质量问题，人工验证仍是最终质量把关环节。",
            "hello-agents-chapter-12",
            "人工验证仍然是不可或缺的",
        ),
    ),
)


def _source_path(spec: SourceSpec) -> Path:
    return ROOT.joinpath(*Path(spec.local_path).parts)


def seed_raw_sources(external_root: Path) -> None:
    for spec in SOURCES:
        if spec.external_directory is None:
            origin = ROOT.joinpath(*Path(spec.relative_path).parts)
        else:
            origin = external_root / spec.external_directory
            origin = origin.joinpath(*Path(spec.relative_path).parts)
        if not origin.is_file():
            raise FileNotFoundError(f"固定来源不存在：{origin}")
        normalized = normalize_text(origin.read_text(encoding="utf-8"))
        actual_hash = content_hash(normalized)
        if actual_hash != spec.expected_hash:
            raise ValueError(
                f"固定来源内容与预期提交不一致：{spec.source_id} "
                f"expected={spec.expected_hash} actual={actual_hash}"
            )
        destination = _source_path(spec)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(normalized.encode("utf-8"))


def load_documents() -> tuple[SourceManifest, tuple[SourceDocument, ...]]:
    entries: list[SourceManifestEntry] = []
    documents: list[SourceDocument] = []
    for spec in SOURCES:
        path = _source_path(spec)
        if not path.is_file():
            raise FileNotFoundError(
                f"缺少仓库内固定来源副本：{spec.local_path}；"
                "首次构建请传入 --seed-source-root"
            )
        raw = path.read_bytes()
        content = raw.decode("utf-8")
        if raw != normalize_text(content).encode("utf-8"):
            raise ValueError(f"raw 来源未使用规范化 UTF-8/LF 字节：{spec.source_id}")
        actual_hash = content_hash(content)
        if actual_hash != spec.expected_hash:
            raise ValueError(
                f"raw 来源哈希不匹配：{spec.source_id} "
                f"expected={spec.expected_hash} actual={actual_hash}"
            )
        entry = SourceManifestEntry(
            source_id=spec.source_id,
            title=spec.title,
            source_url=spec.source_url,
            repository=spec.repository,
            commit_sha=spec.commit_sha,
            relative_path=spec.relative_path,
            fetched_at=FETCHED_AT,
            content_hash=actual_hash,
            local_path=spec.local_path,
        )
        entries.append(entry)
        documents.append(
            SourceDocument(
                **entry.model_dump(exclude={"local_path"}),
                content=content,
            )
        )
    return SourceManifest(sources=tuple(entries)), tuple(documents)


def _find_chunk(
    chunks: tuple[CorpusChunk, ...], source_id: str, needle: str
) -> CorpusChunk:
    matches = [
        chunk for chunk in chunks if chunk.source_id == source_id and needle in chunk.text
    ]
    if len(matches) != 1:
        raise ValueError(
            f"证据定位必须唯一：source_id={source_id} needle={needle!r} "
            f"matches={len(matches)}"
        )
    return matches[0]


def _find_controlled_chunk(
    chunks: tuple[CorpusChunk, ...], heading: str
) -> CorpusChunk:
    matches = [
        chunk
        for chunk in chunks
        if chunk.source_id == "controlled-benchmark-distractors"
        and chunk.heading_path
        and chunk.heading_path[-1] == heading
    ]
    if len(matches) != 1:
        raise ValueError(f"受控证据标题必须唯一：heading={heading} matches={len(matches)}")
    return matches[0]


def build_claims(
    chunks: tuple[CorpusChunk, ...],
) -> tuple[tuple[Claim, ...], dict[int, tuple[CorpusChunk, CorpusChunk, CorpusChunk, CorpusChunk]]]:
    claims: list[Claim] = []
    topic_chunks: dict[int, tuple[CorpusChunk, CorpusChunk, CorpusChunk, CorpusChunk]] = {}
    for topic in TOPICS:
        number = f"{topic.number:02d}"
        first_chunk = _find_chunk(chunks, topic.first.source_id, topic.first.needle)
        second_chunk = _find_chunk(chunks, topic.second.source_id, topic.second.needle)
        if first_chunk.chunk_id == second_chunk.chunk_id:
            raise ValueError(f"主题 {number} 的两条当前主张必须使用不同证据块")
        control_a_chunk = _find_controlled_chunk(chunks, f"CTRL-{number}-A")
        control_b_chunk = _find_controlled_chunk(chunks, f"CTRL-{number}-B")
        current_ids = (f"current-{number}-a", f"current-{number}-b")
        control_ids = (f"distractor-{number}-a", f"distractor-{number}-b")
        adjudication_index = 0 if topic.number % 2 == 1 else 1
        adjudication_id = current_ids[adjudication_index]
        claims.extend(
            (
                Claim(
                    claim_id=current_ids[0],
                    statement=topic.first.statement,
                    evidence_chunk_ids=(first_chunk.chunk_id,),
                    valid_from=FETCHED_AT,
                    valid_until=None,
                    conflicts_with=control_ids if adjudication_index == 0 else (),
                ),
                Claim(
                    claim_id=current_ids[1],
                    statement=topic.second.statement,
                    evidence_chunk_ids=(second_chunk.chunk_id,),
                    valid_from=FETCHED_AT,
                    valid_until=None,
                    conflicts_with=control_ids if adjudication_index == 1 else (),
                ),
                Claim(
                    claim_id=control_ids[0],
                    statement=control_a_chunk.text,
                    evidence_chunk_ids=(control_a_chunk.chunk_id,),
                    valid_from=None,
                    valid_until=OUTDATED_UNTIL,
                    conflicts_with=(adjudication_id, control_ids[1]),
                ),
                Claim(
                    claim_id=control_ids[1],
                    statement=control_b_chunk.text,
                    evidence_chunk_ids=(control_b_chunk.chunk_id,),
                    valid_from=None,
                    valid_until=None,
                    conflicts_with=(adjudication_id, control_ids[0]),
                ),
            )
        )
        topic_chunks[topic.number] = (
            first_chunk,
            second_chunk,
            control_a_chunk,
            control_b_chunk,
        )
    return tuple(claims), topic_chunks


def enrich_chunks(
    chunks: tuple[CorpusChunk, ...], claims: tuple[Claim, ...]
) -> tuple[CorpusChunk, ...]:
    claim_ids_by_chunk: dict[str, list[str]] = {}
    for claim in claims:
        for chunk_id in claim.evidence_chunk_ids:
            claim_ids_by_chunk.setdefault(chunk_id, []).append(claim.claim_id)
    return tuple(
        chunk.model_copy(
            update={
                "token_terms": tuple(tokenize(chunk.text)),
                "claim_ids": tuple(sorted(claim_ids_by_chunk.get(chunk.chunk_id, ()))),
            }
        )
        for chunk in chunks
    )


def _environment(
    environment_id: str,
    visible: tuple[str, ...],
    research: tuple[str, ...],
    excluded: tuple[str, ...],
) -> KnowledgeEnvironment:
    return KnowledgeEnvironment(
        environment_id=environment_id,
        visible_chunk_ids=visible,
        research_chunk_ids=research,
        excluded_chunk_ids=excluded,
        environment_hash=compute_environment_hash(
            environment_id, visible, research, excluded
        ),
    )


def _opaque_id(prefix: str, base_question_id: str, slot: int) -> str:
    digest = sha256_hex(
        {
            "base_question_id": base_question_id,
            "identity_kind": prefix,
            "variant_slot": slot,
        }
    )
    return f"{prefix}-{digest[:16]}"


def build_drafts(
    topic_chunks: dict[int, tuple[CorpusChunk, CorpusChunk, CorpusChunk, CorpusChunk]],
) -> tuple[dict[str, object], ...]:
    drafts: list[dict[str, object]] = []
    for topic in TOPICS:
        number = f"{topic.number:02d}"
        first, second, control_a, control_b = topic_chunks[topic.number]
        next_number = topic.number % len(TOPICS) + 1
        next_next_number = next_number % len(TOPICS) + 1
        next_first, _, next_control_a, next_control_b = topic_chunks[next_number]
        _, _, next_next_control_a, _ = topic_chunks[next_next_number]
        current_ids = (f"current-{number}-a", f"current-{number}-b")
        current_chunks = (first, second)
        missing_index = 0 if topic.number % 2 == 1 else 1
        missing_chunk = current_chunks[missing_index]
        known_chunk = current_chunks[1 - missing_index]
        missing_claim_ids = (current_ids[missing_index],)
        evidence = (first.chunk_id, second.chunk_id)
        allowed_sources = tuple(dict.fromkeys((first.source_id, second.source_id)))
        variants = (
            (
                0,
                CaseCategory.LOCAL_SUFFICIENT,
                (
                    first.chunk_id,
                    second.chunk_id,
                    next_control_a.chunk_id,
                    next_control_b.chunk_id,
                ),
                (next_first.chunk_id,),
                (next_next_control_a.chunk_id,),
                (),
                False,
                "两条当前必需主张均可见；研究池和受控块只含跨主题中性证据。",
            ),
            (
                1,
                CaseCategory.LOCAL_PARTIAL,
                (
                    known_chunk.chunk_id,
                    next_first.chunk_id,
                    next_control_a.chunk_id,
                    next_control_b.chunk_id,
                ),
                (missing_chunk.chunk_id,),
                (next_next_control_a.chunk_id,),
                missing_claim_ids,
                True,
                "一条当前主张可见，另一条只在研究池；其余块为跨主题中性证据。",
            ),
            (
                2,
                CaseCategory.OUTDATED,
                (
                    known_chunk.chunk_id,
                    next_first.chunk_id,
                    control_a.chunk_id,
                    next_control_a.chunk_id,
                ),
                (missing_chunk.chunk_id,),
                (control_b.chunk_id,),
                missing_claim_ids,
                True,
                "可见池含具有截止时间的互斥命题，当前裁决证据位于研究池。",
            ),
            (
                3,
                CaseCategory.CONFLICT,
                (
                    known_chunk.chunk_id,
                    next_first.chunk_id,
                    control_a.chunk_id,
                    control_b.chunk_id,
                ),
                (missing_chunk.chunk_id,),
                (next_control_a.chunk_id,),
                missing_claim_ids,
                True,
                "可见池含两条受控冲突主张，当前裁决证据位于研究池。",
            ),
        )
        base_question_id = f"base-{number}"
        for slot, category, visible, research, excluded, missing, need_research, reason in variants:
            environment_id = _opaque_id("env", base_question_id, slot)
            environment = _environment(environment_id, visible, research, excluded)
            case = BenchmarkCase(
                case_id=_opaque_id("case", base_question_id, slot),
                base_question_id=base_question_id,
                question=topic.question,
                category=category,
                annotation_reason=reason,
                required_claims=(topic.first.statement, topic.second.statement),
                allowed_source_ids=allowed_sources,
                answer_key=(topic.first.statement, topic.second.statement),
                local_knowledge_ids=environment.visible_chunk_ids,
                need_research=need_research,
                environment_id=environment.environment_id,
                required_claim_ids=current_ids,
                missing_claim_ids=missing,
                evidence_chunk_ids=evidence,
                draft_status="validated",
                review_status="pending",
                human_review_status="not_required",
            )
            drafts.append(
                {
                    "case": case.model_dump(mode="json"),
                    "environment": environment.model_dump(mode="json"),
                }
            )
    return tuple(drafts)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((canonical_json(payload) + "\n").encode("utf-8"))


def _write_jsonl(path: Path, items: tuple[object, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(f"{canonical_json(item)}\n" for item in items)
    path.write_bytes(text.encode("utf-8"))


def build() -> None:
    manifest, documents = load_documents()
    base_chunks = tuple(
        chunk for document in documents for chunk in chunk_markdown(document)
    )
    claims, topic_chunks = build_claims(base_chunks)
    chunks = enrich_chunks(base_chunks, claims)
    drafts = build_drafts(topic_chunks)
    cases = tuple(BenchmarkCase.model_validate(draft["case"]) for draft in drafts)
    environments = tuple(
        KnowledgeEnvironment.model_validate(draft["environment"]) for draft in drafts
    )
    issues = validate_dataset(cases, environments, chunks, claims)
    if issues:
        rendered = "\n".join(
            f"{issue.case_id} {issue.code}: {issue.message} refs={issue.refs}"
            for issue in issues
        )
        raise ValueError(f"夹具规则校验失败：\n{rendered}")

    _write_json(
        ROOT / "fixtures" / "sources" / "manifest.json",
        manifest.model_dump(mode="json"),
    )
    _write_jsonl(
        ROOT / "fixtures" / "corpus" / "documents.jsonl",
        tuple(document.model_dump(mode="json") for document in documents),
    )
    _write_jsonl(
        ROOT / "fixtures" / "corpus" / "chunks.jsonl",
        tuple(chunk.model_dump(mode="json") for chunk in chunks),
    )
    _write_jsonl(
        ROOT / "fixtures" / "corpus" / "claims.jsonl",
        tuple(claim.model_dump(mode="json") for claim in claims),
    )
    _write_jsonl(ROOT / "fixtures" / "benchmark" / "drafts.jsonl", drafts)
    for name in ("reviews.jsonl", "change_log.jsonl"):
        path = ROOT / "fixtures" / "benchmark" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从仓库内固定 raw 来源确定性构建第二天语料与候选基准"
    )
    parser.add_argument(
        "--seed-source-root",
        type=Path,
        help="首次构建时，从包含两个固定只读克隆的目录写入规范化 raw 副本",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.seed_source_root is not None:
        seed_raw_sources(args.seed_source_root.resolve())
    build()


if __name__ == "__main__":
    main()
