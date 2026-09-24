import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from knowledge_gap_agent.benchmark.models import KnowledgeEnvironment
from knowledge_gap_agent.benchmark.validation import (
    LABEL_FIELDS,
    build_model_input_payload,
    build_runtime_payload,
    validate_dataset,
)
from knowledge_gap_agent.contracts.benchmark import (
    BenchmarkCase,
    CaseCategory,
    DraftStatus,
    HumanReviewStatus,
    ReviewStatus,
)
from knowledge_gap_agent.corpus.manifest import load_source_manifest, verify_sources
from knowledge_gap_agent.corpus.models import Claim, CorpusChunk, SourceDocument
from knowledge_gap_agent.corpus.normalize import normalize_text
from knowledge_gap_agent.utils.canonical import canonical_json, sha256_hex


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_day2_fixtures.py"
MANIFEST_PATH = ROOT / "fixtures" / "sources" / "manifest.json"
DOCUMENTS_PATH = ROOT / "fixtures" / "corpus" / "documents.jsonl"
CHUNKS_PATH = ROOT / "fixtures" / "corpus" / "chunks.jsonl"
CLAIMS_PATH = ROOT / "fixtures" / "corpus" / "claims.jsonl"
DRAFTS_PATH = ROOT / "fixtures" / "benchmark" / "drafts.jsonl"
REVIEWS_PATH = ROOT / "fixtures" / "benchmark" / "reviews.jsonl"
CHANGE_LOG_PATH = ROOT / "fixtures" / "benchmark" / "change_log.jsonl"
CONTROLLED_SOURCE_PATH = (
    ROOT / "fixtures" / "sources" / "controlled" / "benchmark-distractors.md"
)

EXPECTED_SOURCE_HASHES = {
    "project-experiment-contract": "eedddd18ed841e8df3aba21a5568daed3952f060df4a2b4715432cfbf95c77cf",
    "project-ai-coding-guide": "6e4e4592dbe85587c7984b0d79562657dda97701f1f14037262b6081fc9fe569",
    "project-decisions": "2d182cc774986354fdfc526a0fbc01ff654edcce4851e95b58bfee4297bd2502",
    "controlled-benchmark-distractors": "b94b3c1acf993941667dfb37d0033d73c9ce4e59d467680f8eab5fbf97a7ea5d",
    "agent-learning-hub-readme": "0a2a4329a547a54462ab2f5a13525e8233901588486e57b0afadde18097d20d6",
    "hello-agents-chapter-7": "a6818e1957eb62e6983ab07e381f0a0d73aef13026152aa87bfa97245922b78e",
    "hello-agents-chapter-8": "97262da77f3ae5fa9745e532bb0fcf14066546775da8644172f40d1a8048dce6",
    "hello-agents-chapter-12": "4015fad8532c0b8f3406b272d938f1f130c7f11832e1487298055f7b0708e333",
}
EXPECTED_COMMITS = {
    "project-experiment-contract": "19e13d048cf0e6ba11695f4d6dd954cb8a364ebb",
    "project-ai-coding-guide": "55e1c2f40356558c0cfafcb639830201000af20f",
    "project-decisions": "55e1c2f40356558c0cfafcb639830201000af20f",
    "controlled-benchmark-distractors": "a866aee6b000331ba2fa0e4079b3c8b902e52e20",
    "agent-learning-hub-readme": "dddf777dde6788228136862f270203424a28efbc",
    "hello-agents-chapter-7": "5caceca4e4c9a3d25cd14627881436953f4d6912",
    "hello-agents-chapter-8": "5caceca4e4c9a3d25cd14627881436953f4d6912",
    "hello-agents-chapter-12": "5caceca4e4c9a3d25cd14627881436953f4d6912",
}
EXPECTED_RELATIVE_PATHS = {
    "project-experiment-contract": "docs/实验合同.md",
    "project-ai-coding-guide": "docs/AI_CODING_GUIDE.md",
    "project-decisions": "docs/decisions.md",
    "controlled-benchmark-distractors": (
        "fixtures/sources/controlled/benchmark-distractors.md"
    ),
    "agent-learning-hub-readme": "README.md",
    "hello-agents-chapter-7": "docs/chapter7/第七章 构建你的Agent框架.md",
    "hello-agents-chapter-8": "docs/chapter8/第八章 记忆与检索.md",
    "hello-agents-chapter-12": "docs/chapter12/第十二章 智能体性能评估.md",
}
EXPECTED_CATEGORIES = {
    CaseCategory.LOCAL_SUFFICIENT,
    CaseCategory.LOCAL_PARTIAL,
    CaseCategory.OUTDATED,
    CaseCategory.CONFLICT,
}
EXPECTED_FILES = (
    SCRIPT,
    MANIFEST_PATH,
    DOCUMENTS_PATH,
    CHUNKS_PATH,
    CLAIMS_PATH,
    DRAFTS_PATH,
    REVIEWS_PATH,
    CHANGE_LOG_PATH,
)
CURRENT_CLAIM_CONTRACTS = {
    "current-01-a": (
        "规范 JSON 必须按映射键排序、使用 UTF-8，并拒绝非有限数值。",
        ("映射键排序", "UTF-8 编码", "禁止 `NaN` 和无穷大"),
    ),
    "current-01-b": (
        "会改变实验输入、边界或随机性的冻结变量都必须进入 config_hash。",
        ("`random_seed` 均进入 `config_hash`", "输入、执行边界或随机性"),
    ),
    "current-02-a": (
        "冻结模型的集合字段在 Python 内部使用 tuple，JSON 持久化仍输出数组。",
        ("内部使用 `tuple`", "JSONL 持久化继续输出数组"),
    ),
    "current-02-b": (
        "冻结模型不应使用不可变 list 子类，因为基类方法可绕过覆盖并破坏深复制和 Pickle。",
        ("不要实现“不可变 `list` 子类”", "基类方法可以绕过", "深复制和 Pickle"),
    ),
    "current-03-a": (
        "每个新增行为先写目标测试并观察它因功能缺失而失败，再写最小实现。",
        ("写一个只表达目标行为的测试", "因功能缺失而失败", "写最少生产代码"),
    ),
    "current-03-b": (
        "已发现的实际缺陷应由回归测试固定其复现边界。",
        ("回归测试", "固定已发现缺陷"),
    ),
    "current-04-a": (
        "独立任务先做规格审查，通过后再做代码质量审查。",
        ("1. **规格审查", "2. **代码质量审查"),
    ),
    "current-04-b": (
        "子任务一次只承担实现、规格审查或质量审查中的一种角色。",
        ("子任务一次只承担一种角色", "实现、规格审查或质量审查"),
    ),
    "current-05-a": (
        "语料模块负责来源、规范化、切块和证据，不负责检索排名或搜索决策。",
        ("`src/knowledge_gap_agent/corpus/`", "排名、搜索决策、模型调用"),
    ),
    "current-05-b": (
        "新增实现不得复制既有哈希、校验或状态机逻辑，出现重复应先校正上下文。",
        ("停止实现，先校正上下文", "复制了已有哈希、校验或状态机逻辑"),
    ),
    "current-06-a": (
        "Message 的 role 被限制为 user、assistant、system、tool 四种标准角色。",
        ('`"user"`', '`"assistant"`', '`"system"`', '`"tool"`', "严格限制"),
    ),
    "current-06-b": (
        "Agent 基类用 Message 列表管理历史，具体调用会组合系统、历史与当前用户消息。",
        ("添加系统消息", "添加历史消息", "添加当前用户消息"),
    ),
    "current-07-a": (
        "工作记忆面向当前会话的临时信息，容量受限并在会话结束后清理。",
        ("当前对话的上下文信息", "容量被有意限制", "会话结束后便会自动清理"),
    ),
    "current-07-b": (
        "语义记忆保存抽象概念、规则和知识，可结合图数据库与向量数据库。",
        ("抽象的概念、规则和知识", "Neo4j图数据库和Qdrant向量数据库"),
    ),
    "current-08-a": (
        "RAG 数据准备包含数据提取、文本分割和向量化，应用阶段检索后注入提示词再生成答案。",
        ("数据提取", "文本分割", "向量化", "注入Prompt", "生成答案"),
    ),
    "current-08-b": (
        "异构文档可先转换为 Markdown，再按结构分块、向量化并进入存储检索。",
        ("MarkItDown转换", "Markdown文本", "智能分块", "向量化", "存储检索"),
    ),
    "current-09-a": (
        "知识缺口实验至少定义任务成功率、Precision、Recall、F1 和错误充分率。",
        ("`TaskSuccess", "`Precision", "`Recall", "`F1", "`FalseSufficientRate"),
    ),
    "current-09-b": (
        "不同智能体任务需要不同评估方法，工具调用与问答不能只用同一简单对错标准。",
        ("评估标准的多样性", "工具调用需要检查函数签名", "问答任务需要评估语义相似度"),
    ),
    "current-10-a": (
        "runtime、labels、audit 必须物理分离，运行载荷按字段白名单构造。",
        ("runtime.jsonl", "labels.jsonl", "audit.jsonl", "字段白名单"),
    ),
    "current-10-b": (
        "正式冻结必须重新计算人工门禁，不信任调用方手填的状态字段。",
        ("正式冻结重新计算门禁", "不信任调用方手填的状态字段"),
    ),
    "current-11-a": (
        "面向项目的学习者应按 Project Ladder 逐档完成可运行作品。",
        ("Project Ladder", "每一档做一个可运行作品"),
    ),
    "current-11-b": (
        "评估阶段应使用固定测试集，并记录成功率、失败原因、工具调用次数、成本和延迟。",
        ("准备固定测试集", "成功率、失败原因、工具调用次数、成本、延迟"),
    ),
    "current-12-a": (
        "过时、冲突、低置信度、被退回或曾规则失败的样本必须进入人工审核。",
        ("过时、冲突、低置信度", "必须进入人工审核"),
    ),
    "current-12-b": (
        "自动化评估可能遗漏严格推理或主观质量问题，人工验证仍是最终质量把关环节。",
        ("自动化评估可能遗漏的问题", "人工验证仍然是不可或缺的"),
    ),
}
CONTROLLED_EXCLUSIVITY_MARKERS = {
    "01": ("禁止排序映射键或数组元素", "同时排序所有映射键和所有数组元素"),
    "02": ("普通 `list` 是唯一允许的集合容器", "自定义不可变 `list` 子类是唯一允许的集合容器"),
    "03": ("实现完成后才允许编写测试", "测试必须在实现前写好"),
    "04": ("只允许原实现者完成一次合并自审", "必须先做代码质量审查，再做规格审查"),
    "05": ("研究决策的唯一责任模块是 benchmark", "研究决策的唯一责任模块是 corpus"),
    "06": ("唯一消息契约是包含全部上下文的单个自由字符串", "唯一消息契约只保留最新用户文本"),
    "07": ("唯一记忆介质是无限增长的会话列表", "唯一记忆介质是外部向量数据库"),
    "08": ("唯一处理路径是把完整原始文件直接放入提示词", "唯一处理路径是把最高分块直接作为最终答案"),
    "09": ("唯一评测判据是任务准确率", "唯一评测判据是平均响应延迟"),
    "10": (
        "正式冻结只能信任调用方手填的人工审核状态",
        "正式冻结必须忽略所有人工审核状态并无条件自动通过",
    ),
    "11": ("完成全部框架与数学理论前禁止运行示例", "只允许复制并运行完整框架"),
    "12": ("唯一自动批准条件是两个模型结论一致", "唯一自动批准条件是复核置信度不低于 `0.8`"),
}


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture(scope="module")
def fixture_data():
    missing = [str(path.relative_to(ROOT)) for path in EXPECTED_FILES if not path.is_file()]
    if missing:
        pytest.skip(f"第二天夹具尚未生成：{missing}")

    documents = tuple(SourceDocument.model_validate(row) for row in read_jsonl(DOCUMENTS_PATH))
    chunks = tuple(CorpusChunk.model_validate(row) for row in read_jsonl(CHUNKS_PATH))
    claims = tuple(Claim.model_validate(row) for row in read_jsonl(CLAIMS_PATH))
    drafts = tuple(read_jsonl(DRAFTS_PATH))
    cases = tuple(BenchmarkCase.model_validate(row["case"]) for row in drafts)
    environments = tuple(
        KnowledgeEnvironment.model_validate(row["environment"]) for row in drafts
    )
    return documents, chunks, claims, drafts, cases, environments


def test_required_fixture_files_exist() -> None:
    missing = [str(path.relative_to(ROOT)) for path in EXPECTED_FILES if not path.is_file()]
    assert not missing, f"缺少第二天夹具文件：{missing}"


def test_manifest_fixes_eight_commit_pinned_normalized_sources(fixture_data) -> None:
    documents, *_ = fixture_data
    manifest = load_source_manifest(MANIFEST_PATH)

    assert len(manifest.sources) == 8
    assert {source.source_id: source.content_hash for source in manifest.sources} == (
        EXPECTED_SOURCE_HASHES
    )
    assert {source.source_id: source.commit_sha for source in manifest.sources} == (
        EXPECTED_COMMITS
    )
    assert {source.source_id: source.relative_path for source in manifest.sources} == (
        EXPECTED_RELATIVE_PATHS
    )
    assert verify_sources(manifest, ROOT) == []
    assert all(
        source.source_url.endswith(
            f"/{source.commit_sha}/{source.relative_path}"
        )
        for source in manifest.sources
    )
    assert all(source.local_path.startswith("fixtures/sources/raw/") for source in manifest.sources)
    assert all(source.relative_path for source in manifest.sources)
    assert all(source.fetched_at.isoformat() == "2026-09-24T00:00:00+08:00" for source in manifest.sources)

    documents_by_id = {document.source_id: document for document in documents}
    assert set(documents_by_id) == set(EXPECTED_SOURCE_HASHES)
    for source in manifest.sources:
        raw = (ROOT / source.local_path).read_text(encoding="utf-8")
        assert raw == normalize_text(raw)
        assert documents_by_id[source.source_id].content == raw
        assert documents_by_id[source.source_id].content_hash == source.content_hash


def test_drafts_form_exactly_twelve_by_four_matrix(fixture_data) -> None:
    _, _, _, drafts, cases, environments = fixture_data

    assert len(drafts) == len(cases) == len(environments) == 48
    assert len({case.case_id for case in cases}) == 48
    assert len({environment.environment_id for environment in environments}) == 48
    assert len({case.base_question_id for case in cases}) == 12
    by_base: dict[str, list[BenchmarkCase]] = defaultdict(list)
    for case in cases:
        by_base[case.base_question_id].append(case)
    assert all(len(group) == 4 for group in by_base.values())
    assert all({case.category for case in group} == EXPECTED_CATEGORIES for group in by_base.values())
    assert Counter(case.category for case in cases) == Counter(
        {category: 12 for category in EXPECTED_CATEGORIES}
    )


def test_base_10_question_and_current_claims_share_the_freeze_gate_decision(fixture_data) -> None:
    _, _, claims, _, cases, _ = fixture_data
    base_cases = [case for case in cases if case.base_question_id == "base-10"]

    assert {case.question for case in base_cases} == {
        "运行、标签和审计数据应如何隔离，正式冻结应如何验证人工门禁？"
    }
    assert {case.required_claims for case in base_cases} == {
        (
            "runtime、labels、audit 必须物理分离，运行载荷按字段白名单构造。",
            "正式冻结必须重新计算人工门禁，不信任调用方手填的状态字段。",
        )
    }
    claims_by_id = {claim.claim_id: claim for claim in claims}
    assert set(claims_by_id["current-10-b"].conflicts_with) == {
        "distractor-10-a", "distractor-10-b"
    }


def test_case_and_environment_ids_are_opaque(fixture_data) -> None:
    *_, cases, environments = fixture_data

    assert all(re.fullmatch(r"case-[0-9a-f]{16}", case.case_id) for case in cases)
    assert all(
        re.fullmatch(r"env-[0-9a-f]{16}", environment.environment_id)
        for environment in environments
    )


def test_simple_structural_features_have_identical_category_distributions(
    fixture_data,
) -> None:
    _, chunks, _, _, cases, environments = fixture_data
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    environments_by_id = {
        environment.environment_id: environment for environment in environments
    }
    signatures: dict[CaseCategory, Counter[tuple[int, int, int, int]]] = {
        category: Counter() for category in EXPECTED_CATEGORIES
    }
    missing_positions: dict[CaseCategory, Counter[tuple[int, ...]]] = {
        category: Counter() for category in EXPECTED_CATEGORIES
    }

    for case in cases:
        environment = environments_by_id[case.environment_id]
        controlled_visible = sum(
            chunks_by_id[chunk_id].source_id == "controlled-benchmark-distractors"
            for chunk_id in environment.visible_chunk_ids
        )
        signatures[case.category][
            (
                len(environment.visible_chunk_ids),
                len(environment.research_chunk_ids),
                len(environment.excluded_chunk_ids),
                controlled_visible,
            )
        ] += 1
        missing_positions[case.category][
            tuple(
                case.required_claim_ids.index(claim_id)
                for claim_id in case.missing_claim_ids
            )
        ] += 1

    expected_signature = Counter({(4, 1, 1, 2): 12})
    assert all(distribution == expected_signature for distribution in signatures.values())
    expected_missing_positions = Counter({(0,): 6, (1,): 6})
    for category in (
        CaseCategory.LOCAL_PARTIAL,
        CaseCategory.OUTDATED,
        CaseCategory.CONFLICT,
    ):
        assert missing_positions[category] == expected_missing_positions


def test_every_draft_uses_valid_pending_unreviewed_statuses(fixture_data) -> None:
    *_, cases, _ = fixture_data

    assert all(case.draft_status is DraftStatus.VALIDATED for case in cases)
    assert all(case.review_status is ReviewStatus.PENDING for case in cases)
    assert all(
        case.human_review_status is HumanReviewStatus.NOT_REQUIRED for case in cases
    )
    assert all(len(case.required_claim_ids) == 2 for case in cases)


def test_all_models_and_dataset_rules_validate(fixture_data) -> None:
    _, chunks, claims, _, cases, environments = fixture_data

    assert validate_dataset(cases, environments, chunks, claims) == ()


def test_claim_chunk_links_are_bidirectional_and_sources_are_allowed(fixture_data) -> None:
    _, chunks, claims, _, cases, _ = fixture_data
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    claims_by_id = {claim.claim_id: claim for claim in claims}

    for chunk in chunks:
        for claim_id in chunk.claim_ids:
            assert chunk.chunk_id in claims_by_id[claim_id].evidence_chunk_ids
    for claim in claims:
        for chunk_id in claim.evidence_chunk_ids:
            assert claim.claim_id in chunks_by_id[chunk_id].claim_ids
            if claim.claim_id.startswith("current-"):
                assert chunks_by_id[chunk_id].source_id != "controlled-benchmark-distractors"
            else:
                assert claim.claim_id.startswith("distractor-")
                assert chunks_by_id[chunk_id].source_id == "controlled-benchmark-distractors"
    assert Counter(
        "current" if claim.claim_id.startswith("current-") else "distractor"
        for claim in claims
    ) == Counter({"current": 24, "distractor": 24})
    for case in cases:
        evidence_sources = {
            chunks_by_id[chunk_id].source_id for chunk_id in case.evidence_chunk_ids
        }
        assert evidence_sources <= set(case.allowed_source_ids)


def test_all_current_claims_have_direct_semantic_evidence(fixture_data) -> None:
    _, chunks, claims, *_ = fixture_data
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    claims_by_id = {claim.claim_id: claim for claim in claims}

    assert set(CURRENT_CLAIM_CONTRACTS) == {
        claim_id for claim_id in claims_by_id if claim_id.startswith("current-")
    }
    for claim_id, (statement, markers) in CURRENT_CLAIM_CONTRACTS.items():
        claim = claims_by_id[claim_id]
        assert claim.statement == statement, claim_id
        assert len(claim.evidence_chunk_ids) == 1, claim_id
        evidence = chunks_by_id[claim.evidence_chunk_ids[0]]
        assert all(marker in evidence.text for marker in markers), claim_id


def test_controlled_source_uses_neutral_ids_and_explicit_exclusive_propositions() -> None:
    text = CONTROLLED_SOURCE_PATH.read_text(encoding="utf-8")

    assert not re.search(r"\b(?:OLD|ALT)\b|已过时声明|冲突候选声明", text)
    assert re.findall(r"^### (CTRL-\d{2}-[AB])$", text, flags=re.MULTILINE) == [
        f"CTRL-{number:02d}-{polarity}"
        for number in range(1, 13)
        for polarity in ("A", "B")
    ]
    for first_marker, second_marker in CONTROLLED_EXCLUSIVITY_MARKERS.values():
        assert text.count(first_marker) == 1
        assert text.count(second_marker) == 1


def test_generated_controlled_claims_preserve_twelve_semantic_exclusivity_canaries(
    fixture_data,
) -> None:
    _, chunks, claims, *_ = fixture_data
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    claims_by_id = {claim.claim_id: claim for claim in claims}

    for number, (first_marker, second_marker) in CONTROLLED_EXCLUSIVITY_MARKERS.items():
        first_id = f"distractor-{number}-a"
        second_id = f"distractor-{number}-b"
        assert first_id in claims_by_id
        assert second_id in claims_by_id
        first = claims_by_id[first_id]
        second = claims_by_id[second_id]
        assert second_id in first.conflicts_with
        assert first_id in second.conflicts_with
        assert first_marker in chunks_by_id[first.evidence_chunk_ids[0]].text
        assert second_marker in chunks_by_id[second.evidence_chunk_ids[0]].text


def test_environment_pools_are_disjoint_and_follow_derivation_rules(fixture_data) -> None:
    _, chunks, claims, _, cases, environments = fixture_data
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    claims_by_id = {claim.claim_id: claim for claim in claims}
    environments_by_id = {
        environment.environment_id: environment for environment in environments
    }

    for case in cases:
        environment = environments_by_id[case.environment_id]
        visible = set(environment.visible_chunk_ids)
        research = set(environment.research_chunk_ids)
        excluded = set(environment.excluded_chunk_ids)
        assert not (visible & research or visible & excluded or research & excluded)
        visible_claims = {
            claim_id for chunk_id in visible for claim_id in chunks_by_id[chunk_id].claim_ids
        }
        research_claims = {
            claim_id for chunk_id in research for claim_id in chunks_by_id[chunk_id].claim_ids
        }
        required = set(case.required_claim_ids)
        if case.category is CaseCategory.LOCAL_SUFFICIENT:
            assert required <= visible_claims
            assert case.missing_claim_ids == ()
        elif case.category is CaseCategory.LOCAL_PARTIAL:
            assert len(case.missing_claim_ids) == 1
            assert set(case.missing_claim_ids) <= research_claims
            assert len(required & visible_claims) == 1
        elif case.category is CaseCategory.OUTDATED:
            expired_visible = {
                claim_id
                for claim_id in visible_claims
                if claims_by_id[claim_id].valid_until is not None
            }
            assert expired_visible
            assert set(case.missing_claim_ids) <= research_claims
        else:
            controlled_visible = {
                claim_id for claim_id in visible_claims if claim_id.startswith("distractor-")
            }
            assert len(controlled_visible) == 2
            assert any(
                right in claims_by_id[left].conflicts_with
                for left in controlled_visible
                for right in controlled_visible
                if left != right
            )
            assert set(case.missing_claim_ids) <= research_claims


def test_runtime_payloads_contain_no_label_fields(fixture_data) -> None:
    *_, cases, environments = fixture_data
    environments_by_id = {
        environment.environment_id: environment for environment in environments
    }

    for case in cases:
        payload = build_runtime_payload(case, environments_by_id[case.environment_id])
        assert LABEL_FIELDS.isdisjoint(payload)
        rendered = canonical_json(payload).lower()
        forbidden_value_hints = {
            "local_sufficient",
            "local-sufficient",
            "local_partial",
            "local-partial",
            "outdated",
            "conflict",
            "need_research",
            "need-research",
            "research_required",
            "research-required",
            "requires-research",
        }
        assert all(hint not in rendered for hint in forbidden_value_hints)


def test_model_inputs_hide_envelope_identifiers_and_nonvisible_knowledge(fixture_data) -> None:
    _, chunks, _, _, cases, environments = fixture_data
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    environments_by_id = {
        environment.environment_id: environment for environment in environments
    }
    category_hints = {
        "local_sufficient", "local-sufficient", "local_partial", "local-partial",
        "outdated", "conflict", "need_research", "need-research",
        "research_required", "research-required", "requires-research",
    }

    def strings(value: object):
        if isinstance(value, dict):
            for key, item in value.items():
                yield str(key)
                yield from strings(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from strings(item)
        elif isinstance(value, str):
            yield value

    for case in cases:
        environment = environments_by_id[case.environment_id]
        envelope = build_runtime_payload(case, environment)
        recoverable_slots = []
        for slot in range(4):
            identity = {
                "base_question_id": envelope["base_question_id"],
                "variant_slot": slot,
            }
            expected_case = "case-" + sha256_hex(
                {**identity, "identity_kind": "case"}
            )[:16]
            expected_environment = "env-" + sha256_hex(
                {**identity, "identity_kind": "env"}
            )[:16]
            if (
                envelope["case_id"] == expected_case
                and envelope["environment_id"] == expected_environment
            ):
                recoverable_slots.append(slot)
        assert len(recoverable_slots) == 1

        payload = build_model_input_payload(case, environment, chunks)
        assert set(payload) == {"question", "visible_knowledge"}
        assert payload["question"] == case.question
        assert payload["visible_knowledge"] == [
            chunks_by_id[chunk_id].text for chunk_id in environment.visible_chunk_ids
        ]
        assert len(payload["visible_knowledge"]) == 4
        assert all(
            chunks_by_id[chunk_id].text not in payload["visible_knowledge"]
            for chunk_id in environment.research_chunk_ids + environment.excluded_chunk_ids
        )

        exposed_strings = set(strings(payload))
        forbidden_ids = {
            case.case_id,
            case.base_question_id,
            environment.environment_id,
            *environment.visible_chunk_ids,
            *environment.research_chunk_ids,
            *environment.excluded_chunk_ids,
        }
        assert all(
            identifier not in exposed
            for exposed in exposed_strings
            for identifier in forbidden_ids
        )
        rendered = canonical_json(payload).lower()
        assert all(hint not in rendered for hint in category_hints)


def test_jsonl_is_canonical_and_reviewer_outputs_remain_empty(fixture_data) -> None:
    _, _, _, drafts, _, _ = fixture_data
    assert all(set(draft) == {"case", "environment"} for draft in drafts)
    for path in (DOCUMENTS_PATH, CHUNKS_PATH, CLAIMS_PATH, DRAFTS_PATH):
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines
        assert all(line == canonical_json(json.loads(line)) for line in lines)
    assert REVIEWS_PATH.read_bytes() == b""
    assert CHANGE_LOG_PATH.read_bytes() == b""


def test_rebuild_is_byte_identical_without_external_sources(fixture_data) -> None:
    del fixture_data
    generated = (
        MANIFEST_PATH,
        DOCUMENTS_PATH,
        CHUNKS_PATH,
        CLAIMS_PATH,
        DRAFTS_PATH,
        REVIEWS_PATH,
        CHANGE_LOG_PATH,
    )
    before = {path: path.read_bytes() for path in generated}

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert {path: path.read_bytes() for path in generated} == before
