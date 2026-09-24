import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pytest

import knowledge_gap_agent.benchmark.review as review_module
from knowledge_gap_agent.benchmark.models import (
    HumanRevisionRecord,
    KnowledgeEnvironment,
)
from knowledge_gap_agent.benchmark.review import (
    ReviewDecision,
    ReviewInput,
    ReviewRecord,
    apply_review_gate,
    compute_review_target_hash,
)
from knowledge_gap_agent.benchmark.freeze import freeze_benchmark
from knowledge_gap_agent.benchmark.validation import (
    LABEL_FIELDS,
    build_model_input_payload,
    build_runtime_payload,
    validate_case,
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
REVIEW_INPUTS_PATH = ROOT / "fixtures" / "benchmark" / "review_inputs.jsonl"
REVIEWER_PROMPT_PATH = ROOT / "fixtures" / "benchmark" / "reviewer_prompt_v1.md"
ROUND2_PROMPT_PATH = ROOT / "fixtures" / "benchmark" / "reviewer_revision_prompt_v1.md"
REVIEWS_PATH = ROOT / "fixtures" / "benchmark" / "reviews.jsonl"
HUMAN_REVIEW_QUEUE_PATH = ROOT / "fixtures" / "benchmark" / "human_review_queue.jsonl"
CHANGE_LOG_PATH = ROOT / "fixtures" / "benchmark" / "change_log.jsonl"
REVIEW_HISTORY_DIR = ROOT / "fixtures" / "benchmark" / "review_history"
ROUND1_INPUTS_PATH = REVIEW_HISTORY_DIR / "round-1-inputs.jsonl"
ROUND1_REVIEWS_PATH = REVIEW_HISTORY_DIR / "round-1-reviews.jsonl"
ROUND2_INPUTS_PATH = REVIEW_HISTORY_DIR / "round-2-inputs.jsonl"
ROUND2_REVIEWS_PATH = REVIEW_HISTORY_DIR / "round-2-reviews.jsonl"
PROPOSED_REVIEWS_PATH = ROOT / "fixtures" / "benchmark" / "reviews.proposed.jsonl"
ROUND2_PROPOSED_REVIEWS_PATH = (
    ROOT / "fixtures" / "benchmark" / "reviews.round2.proposed.jsonl"
)
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
    REVIEW_INPUTS_PATH,
    REVIEWER_PROMPT_PATH,
    ROUND2_PROMPT_PATH,
    ROUND1_INPUTS_PATH,
    ROUND1_REVIEWS_PATH,
    ROUND2_INPUTS_PATH,
    ROUND2_REVIEWS_PATH,
    REVIEWS_PATH,
    HUMAN_REVIEW_QUEUE_PATH,
    CHANGE_LOG_PATH,
)
ROUND1_INPUTS_HASH = "b5949208d2b4e0e976015c720d9e04de985e6678431f75bf760faa600b6517a8"
ROUND1_REVIEWS_HASH = "7a112d7125d006f3050bbda1c0e941871c62a99999cb0e1c88fc28b5c1890147"
ROUND1_PROMPT_VERSION = "day2-benchmark-review-v1"
ROUND1_PROMPT_HASH = "5f1f17ef7e6ee0c5f9ca7ebabcb560faca51b23763501e94b27a4fd9c53399b7"
ROUND2_INPUTS_HASH = "4351eebc1cdb6c2391c3c63c5c1e0ae981e1895f6f9f10d9fa17090b716caea3"
ROUND2_REVIEWS_HASH = "94ae44ab604261c580d0705ac7615183810dfd38b782eca1b9aaa6b8759bf85d"
ROUND2_PROMPT_VERSION = "day2-benchmark-rereview-v1"
ROUND2_PROMPT_HASH = "6bd78ec097255e1334ff6829912025ace6060906b04bcaef775103d354baf95f"
REVISED_QUESTIONS = {
    "base-02": (
        "冻结数据模型的集合字段时，自定义不可变 list 子类为何不足，为什么选择 tuple，"
        "并如何保持 JSON 数组兼容？"
    ),
    "base-08": (
        "完整 RAG 如何完成知识准备、检索、提示词注入与回答生成？面对异构文档，"
        "为什么要统一转换为 Markdown，又如何在转换后分块、向量化并进入存储检索？"
    ),
}
ROUND1_REVISE_CASE_IDS = {
    "case-264f4a2113be6ba0",
    "case-2a7053b2297128ee",
    "case-644c0347472ace97",
    "case-7691ad2444757f71",
    "case-7fd2c5ab217bd713",
    "case-a3fa760ae9f821fb",
}
QUALITY_AUDIT_CASE_IDS = {
    "case-afd7e0cfe5fb1afb",
    "case-42caaf49a65abdc0",
}
REVISED_CASE_IDS = ROUND1_REVISE_CASE_IDS | QUALITY_AUDIT_CASE_IDS
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


def copy_fixture_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    shutil.copytree(ROOT / "fixtures", workspace / "fixtures")
    return workspace


def workspace_fixture_path(workspace: Path, path: Path) -> Path:
    return workspace / path.relative_to(ROOT)


def fixture_tree_hashes(workspace: Path) -> dict[Path, str]:
    fixtures = workspace / "fixtures"
    return {
        path.relative_to(workspace): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in fixtures.rglob("*")
        if path.is_file()
    }


def builder_command(workspace: Path) -> list[str]:
    return [sys.executable, str(SCRIPT), "--workspace-root", str(workspace)]


def run_builder(workspace: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        builder_command(workspace),
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def human_revision_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "record_type": "human_review_revision",
        "case_id": "case-human-review-regression",
        "actor": "human-reviewer",
        "reason": "按终审意见更新问题与证据关系。",
        "before_review_target_hash": "a" * 64,
        "after_review_target_hash": "b" * 64,
        "before_summary": "问题未明确要求核对证据时效。",
        "after_summary": "问题已明确要求比较旧主张与当前主张。",
        "changed_at": "2026-09-25T10:00:00+00:00",
    }
    payload.update(updates)
    return payload


@pytest.fixture(autouse=True)
def real_fixtures_remain_unchanged():
    before = fixture_tree_hashes(ROOT)
    yield
    assert fixture_tree_hashes(ROOT) == before


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


def test_rebuild_uses_explicit_isolated_workspace(tmp_path: Path) -> None:
    workspace = copy_fixture_workspace(tmp_path)
    real_before = fixture_tree_hashes(ROOT)

    result = run_builder(workspace)

    assert result.returncode == 0, result.stderr
    assert (workspace / "fixtures/benchmark/drafts.jsonl").is_file()
    assert fixture_tree_hashes(ROOT) == real_before


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
    _, chunks, claims, _, cases, environments = fixture_data
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


def test_every_draft_uses_review_gate_statuses(fixture_data) -> None:
    *_, cases, _ = fixture_data

    assert all(case.draft_status is DraftStatus.VALIDATED for case in cases)
    assert all(case.review_status is ReviewStatus.APPROVED for case in cases)
    assert Counter(case.human_review_status for case in cases) == {
        HumanReviewStatus.NOT_REQUIRED: 24,
        HumanReviewStatus.PENDING: 24,
    }
    assert all(
        case.human_review_status
        is (
            HumanReviewStatus.PENDING
            if case.category in {CaseCategory.OUTDATED, CaseCategory.CONFLICT}
            else HumanReviewStatus.NOT_REQUIRED
        )
        for case in cases
    )
    assert all(len(case.required_claim_ids) == 2 for case in cases)


def test_stored_reviewed_cases_equal_public_gate_results(fixture_data) -> None:
    _, chunks, claims, _, cases, environments = fixture_data
    environments_by_id = {item.environment_id: item for item in environments}
    reviews_by_case = {
        item.case_id: item
        for item in (
            ReviewRecord.model_validate_json(line)
            for line in REVIEWS_PATH.read_text(encoding="utf-8").splitlines()
        )
    }

    for stored_case in cases:
        pending_case = stored_case.model_copy(update={
            "review_status": ReviewStatus.PENDING,
            "human_review_status": HumanReviewStatus.NOT_REQUIRED,
        })
        expected = apply_review_gate(
            pending_case,
            environments_by_id[stored_case.environment_id],
            chunks,
            claims,
            reviews_by_case[stored_case.case_id],
        )
        assert stored_case == expected


def test_all_models_and_dataset_rules_validate(fixture_data) -> None:
    _, chunks, claims, _, cases, environments = fixture_data

    assert validate_dataset(cases, environments, chunks, claims) == ()


def test_each_high_risk_fixture_satisfies_strict_evidence_semantics(
    fixture_data,
) -> None:
    _, chunks, claims, _, cases, environments = fixture_data
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    claims_by_id = {claim.claim_id: claim for claim in claims}
    environments_by_id = {
        environment.environment_id: environment for environment in environments
    }
    known_claim_ids = set(claims_by_id)
    conflict_neighbors = {claim_id: set() for claim_id in known_claim_ids}
    for claim_id, claim in claims_by_id.items():
        for conflict_id in claim.conflicts_with:
            if conflict_id == claim_id or conflict_id not in known_claim_ids:
                continue
            conflict_neighbors[claim_id].add(conflict_id)
            conflict_neighbors[conflict_id].add(claim_id)
    high_risk_cases = [
        case
        for case in cases
        if case.category in {CaseCategory.OUTDATED, CaseCategory.CONFLICT}
    ]

    assert Counter(case.category for case in high_risk_cases) == {
        CaseCategory.OUTDATED: 12,
        CaseCategory.CONFLICT: 12,
    }
    for case in high_risk_cases:
        environment = environments_by_id[case.environment_id]
        issues = validate_case(case, environment, chunks_by_id, claims_by_id)
        assert issues == (), case.case_id
        visible_claim_ids = {
            claim_id
            for chunk_id in environment.visible_chunk_ids
            for claim_id in chunks_by_id[chunk_id].claim_ids
        }
        research_required_ids = (
            set(case.required_claim_ids)
            & {
                claim_id
                for chunk_id in environment.research_chunk_ids
                for claim_id in chunks_by_id[chunk_id].claim_ids
            }
        )

        if case.category is CaseCategory.OUTDATED:
            handoff_witnesses: set[tuple[str, str]] = set()
            for old_id in visible_claim_ids:
                for current_id in conflict_neighbors[old_id] & research_required_ids:
                    old_until = claims_by_id[old_id].valid_until
                    current_from = claims_by_id[current_id].valid_from
                    if (
                        old_id != current_id
                        and old_until is not None
                        and old_until.utcoffset() is not None
                        and current_from is not None
                        and current_from.utcoffset() is not None
                        and old_until < current_from
                    ):
                        handoff_witnesses.add((old_id, current_id))
            assert handoff_witnesses, case.case_id
            assert all(old_id != current_id for old_id, current_id in handoff_witnesses)
        else:
            visible_edges: set[tuple[str, str]] = set()
            for left_id in visible_claim_ids:
                for right_id in conflict_neighbors[left_id] & visible_claim_ids:
                    if left_id < right_id:
                        visible_edges.add((left_id, right_id))
            adjudication_witnesses: set[tuple[str, str, str]] = set()
            for left_id, right_id in visible_edges:
                common_neighbors = (
                    conflict_neighbors[left_id]
                    & conflict_neighbors[right_id]
                    & research_required_ids
                )
                for adjudicator_id in common_neighbors - {left_id, right_id}:
                    adjudication_witnesses.add(
                        (left_id, right_id, adjudicator_id)
                    )
            assert adjudication_witnesses, case.case_id
            assert all(
                len({left_id, right_id, adjudicator_id}) == 3
                for left_id, right_id, adjudicator_id in adjudication_witnesses
            )


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
    _, chunks, claims, _, cases, environments = fixture_data
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


def test_review_inputs_are_complete_auditable_and_reasoning_free(fixture_data) -> None:
    _, chunks, claims, _, cases, environments = fixture_data
    lines = REVIEW_INPUTS_PATH.read_text(encoding="utf-8").splitlines()
    review_inputs = tuple(ReviewInput.model_validate_json(line) for line in lines)
    cases_by_id = {case.case_id: case for case in cases}
    environments_by_id = {
        environment.environment_id: environment for environment in environments
    }
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}

    assert len(review_inputs) == 48
    assert {item.case.case_id for item in review_inputs} == set(cases_by_id)
    for item in review_inputs:
        case = cases_by_id[item.case.case_id]
        environment = environments_by_id[case.environment_id]
        assert item.review_target_hash == compute_review_target_hash(
            case, environment, chunks, claims
        )
        assert len(item.environment.visible_chunks) == 4
        assert len(item.environment.research_chunks) == 1
        assert len(item.environment.excluded_chunks) == 1
        all_chunks = (
            item.environment.visible_chunks
            + item.environment.research_chunks
            + item.environment.excluded_chunks
        )
        assert all(chunk.text == chunks_by_id[chunk.chunk_id].text for chunk in all_chunks)
        assert item.claims
        rendered = canonical_json(item.model_dump(mode="json"))
        assert "annotation_reason" not in rendered
        assert case.annotation_reason not in rendered
        assert "decision" not in type(item).model_fields
        assert "reviewer_confidence" not in type(item).model_fields
        assert "review_status" not in type(item.case).model_fields
        assert "human_review_status" not in type(item.case).model_fields


def test_round1_reviewer_artifacts_are_archived_verbatim_and_bound() -> None:
    assert ROUND1_INPUTS_PATH.is_file()
    assert ROUND1_REVIEWS_PATH.is_file()
    assert not PROPOSED_REVIEWS_PATH.exists()
    assert hashlib.sha256(ROUND1_INPUTS_PATH.read_bytes()).hexdigest() == ROUND1_INPUTS_HASH
    assert hashlib.sha256(ROUND1_REVIEWS_PATH.read_bytes()).hexdigest() == ROUND1_REVIEWS_HASH

    archived_inputs = tuple(
        ReviewInput.model_validate_json(line)
        for line in ROUND1_INPUTS_PATH.read_text(encoding="utf-8").splitlines()
    )
    archived_reviews = tuple(
        ReviewRecord.model_validate_json(line)
        for line in ROUND1_REVIEWS_PATH.read_text(encoding="utf-8").splitlines()
    )
    inputs_by_case = {item.case.case_id: item for item in archived_inputs}

    assert len(archived_inputs) == len(archived_reviews) == 48
    assert Counter(review.decision for review in archived_reviews) == {
        ReviewDecision.APPROVE: 42,
        ReviewDecision.REVISE: 6,
    }
    assert {review.case_id for review in archived_reviews} == set(inputs_by_case)
    assert all(
        review.review_target_hash == inputs_by_case[review.case_id].review_target_hash
        for review in archived_reviews
    )
    assert {review.prompt_version for review in archived_reviews} == {
        ROUND1_PROMPT_VERSION
    }
    assert {review.prompt_hash for review in archived_reviews} == {ROUND1_PROMPT_HASH}


def test_round1_prompt_bytes_match_reviews_and_change_log() -> None:
    prompt_hash = hashlib.sha256(REVIEWER_PROMPT_PATH.read_bytes()).hexdigest()
    archived_reviews = tuple(
        ReviewRecord.model_validate_json(line)
        for line in ROUND1_REVIEWS_PATH.read_text(encoding="utf-8").splitlines()
    )
    revision_model = getattr(review_module, "ReviewRevisionRecord")
    revision_records = tuple(
        revision_model.model_validate_json(line)
        for line in CHANGE_LOG_PATH.read_text(encoding="utf-8").splitlines()[:2]
    )

    assert prompt_hash == ROUND1_PROMPT_HASH
    assert {review.prompt_hash for review in archived_reviews} == {prompt_hash}
    assert {record.prompt_hash for record in revision_records} == {prompt_hash}


def test_round2_reviewer_artifacts_are_archived_verbatim_and_bound() -> None:
    assert ROUND2_INPUTS_PATH.is_file()
    assert ROUND2_REVIEWS_PATH.is_file()
    assert not ROUND2_PROPOSED_REVIEWS_PATH.exists()
    assert hashlib.sha256(ROUND2_INPUTS_PATH.read_bytes()).hexdigest() == (
        ROUND2_INPUTS_HASH
    )
    assert hashlib.sha256(ROUND2_REVIEWS_PATH.read_bytes()).hexdigest() == (
        ROUND2_REVIEWS_HASH
    )
    assert hashlib.sha256(ROUND2_PROMPT_PATH.read_bytes()).hexdigest() == (
        ROUND2_PROMPT_HASH
    )

    current_lines = set(REVIEW_INPUTS_PATH.read_text(encoding="utf-8").splitlines())
    archived_lines = ROUND2_INPUTS_PATH.read_text(encoding="utf-8").splitlines()
    archived_inputs = tuple(ReviewInput.model_validate_json(line) for line in archived_lines)
    archived_reviews = tuple(
        ReviewRecord.model_validate_json(line)
        for line in ROUND2_REVIEWS_PATH.read_text(encoding="utf-8").splitlines()
    )
    inputs_by_case = {item.case.case_id: item for item in archived_inputs}

    assert len(archived_inputs) == len(archived_reviews) == 8
    assert set(archived_lines) <= current_lines
    assert set(inputs_by_case) == REVISED_CASE_IDS
    assert {review.case_id for review in archived_reviews} == REVISED_CASE_IDS
    assert all(review.decision is ReviewDecision.APPROVE for review in archived_reviews)
    assert all(review.reviewer_confidence >= 0.8 for review in archived_reviews)
    assert {review.prompt_version for review in archived_reviews} == {
        ROUND2_PROMPT_VERSION
    }
    assert {review.prompt_hash for review in archived_reviews} == {ROUND2_PROMPT_HASH}
    for review in archived_reviews:
        item = inputs_by_case[review.case_id]
        environment_chunks = {
            chunk.chunk_id
            for chunk in (
                item.environment.visible_chunks
                + item.environment.research_chunks
                + item.environment.excluded_chunks
            )
        }
        assert review.review_target_hash == item.review_target_hash
        assert set(review.evidence_refs) <= environment_chunks


def test_current_reviews_merge_round1_unchanged_and_round2_revised() -> None:
    current_lines = REVIEWS_PATH.read_text(encoding="utf-8").splitlines()
    current = tuple(ReviewRecord.model_validate_json(line) for line in current_lines)
    round1 = {
        item.case_id: item
        for item in (
            ReviewRecord.model_validate_json(line)
            for line in ROUND1_REVIEWS_PATH.read_text(encoding="utf-8").splitlines()
        )
    }
    round2 = {
        item.case_id: item
        for item in (
            ReviewRecord.model_validate_json(line)
            for line in ROUND2_REVIEWS_PATH.read_text(encoding="utf-8").splitlines()
        )
    }
    current_inputs = {
        item.case.case_id: item
        for item in (
            ReviewInput.model_validate_json(line)
            for line in REVIEW_INPUTS_PATH.read_text(encoding="utf-8").splitlines()
        )
    }

    assert len(current) == 48
    assert [item.case_id for item in current] == sorted(item.case_id for item in current)
    assert all(line == canonical_json(json.loads(line)) for line in current_lines)
    assert {item.case_id for item in current} == set(current_inputs)
    for review in current:
        expected = round2.get(review.case_id, round1[review.case_id])
        assert review == expected
        assert review.review_target_hash == current_inputs[review.case_id].review_target_hash
    assert all(review.decision is ReviewDecision.APPROVE for review in current)
    assert all(review.reviewer_confidence >= 0.8 for review in current)
    assert Counter(review.prompt_version for review in current) == {
        ROUND1_PROMPT_VERSION: 40,
        ROUND2_PROMPT_VERSION: 8,
    }


def test_human_review_queue_contains_only_high_risk_pending_cases() -> None:
    cases = tuple(
        BenchmarkCase.model_validate(row["case"])
        for row in read_jsonl(DRAFTS_PATH)
    )
    queue_model = getattr(review_module, "HumanReviewQueueRecord")
    queue_lines = HUMAN_REVIEW_QUEUE_PATH.read_text(encoding="utf-8").splitlines()
    queue = tuple(queue_model.model_validate_json(line) for line in queue_lines)
    reviews = {
        review.case_id: review
        for review in (
            ReviewRecord.model_validate_json(line)
            for line in REVIEWS_PATH.read_text(encoding="utf-8").splitlines()
        )
    }

    assert len(queue) == 24
    assert [item.case_id for item in queue] == sorted(item.case_id for item in queue)
    assert {item.case_id for item in queue} == {
        case.case_id
        for case in cases
        if case.category in {CaseCategory.OUTDATED, CaseCategory.CONFLICT}
    }
    assert all(item.trigger == "high_risk_category" for item in queue)
    assert all(item.decision is ReviewDecision.APPROVE for item in queue)
    assert all(item.category in {CaseCategory.OUTDATED, CaseCategory.CONFLICT} for item in queue)
    assert all(item.review_target_hash == reviews[item.case_id].review_target_hash for item in queue)
    assert all(item.reviewer_confidence == reviews[item.case_id].reviewer_confidence for item in queue)
    assert all(item.prompt_version == reviews[item.case_id].prompt_version for item in queue)
    assert all(
        set(json.loads(line))
        == {
            "case_id", "category", "review_target_hash", "trigger", "decision",
            "reviewer_confidence", "prompt_version",
        }
        for line in queue_lines
    )


def test_first_revision_changes_exactly_eight_review_targets(fixture_data) -> None:
    _, _, _, _, cases, _ = fixture_data
    current_inputs = {
        item.case.case_id: item
        for item in (
            ReviewInput.model_validate_json(line)
            for line in REVIEW_INPUTS_PATH.read_text(encoding="utf-8").splitlines()
        )
    }
    archived_inputs = {
        item.case.case_id: item
        for item in (
            ReviewInput.model_validate_json(line)
            for line in ROUND1_INPUTS_PATH.read_text(encoding="utf-8").splitlines()
        )
    }
    archived_reviews = {
        item.case_id: item
        for item in (
            ReviewRecord.model_validate_json(line)
            for line in ROUND1_REVIEWS_PATH.read_text(encoding="utf-8").splitlines()
        )
    }
    changed = {
        case_id
        for case_id, current in current_inputs.items()
        if current.review_target_hash != archived_inputs[case_id].review_target_hash
    }
    stale_reviews = {
        case_id
        for case_id, review in archived_reviews.items()
        if review.review_target_hash != current_inputs[case_id].review_target_hash
    }

    assert set(current_inputs) == set(archived_inputs) == {case.case_id for case in cases}
    assert changed == stale_reviews == REVISED_CASE_IDS
    assert {
        review.case_id
        for review in archived_reviews.values()
        if review.decision is ReviewDecision.REVISE
    } == ROUND1_REVISE_CASE_IDS
    assert QUALITY_AUDIT_CASE_IDS == {
        case.case_id
        for case in cases
        if case.base_question_id in REVISED_QUESTIONS
        and case.category is CaseCategory.LOCAL_SUFFICIENT
    }
    assert all(
        current_inputs[case_id].review_target_hash
        == archived_inputs[case_id].review_target_hash
        for case_id in set(current_inputs) - REVISED_CASE_IDS
    )
    for case_id in REVISED_CASE_IDS:
        current_payload = current_inputs[case_id].model_dump(
            mode="json", exclude={"review_target_hash"}
        )
        archived_payload = archived_inputs[case_id].model_dump(
            mode="json", exclude={"review_target_hash"}
        )
        archived_payload["case"]["question"] = current_payload["case"]["question"]
        assert current_payload == archived_payload


def test_revised_questions_make_both_required_claims_explicit(fixture_data) -> None:
    _, _, _, _, cases, _ = fixture_data
    for base_question_id, expected_question in REVISED_QUESTIONS.items():
        family = [case for case in cases if case.base_question_id == base_question_id]
        assert len(family) == 4
        assert {case.question for case in family} == {expected_question}
        assert all(case.answer_key == case.required_claims for case in family)


def test_change_log_records_nonhuman_round1_revision(fixture_data) -> None:
    del fixture_data
    revision_model = getattr(review_module, "ReviewRevisionRecord")
    lines = CHANGE_LOG_PATH.read_text(encoding="utf-8").splitlines()
    records = tuple(
        revision_model.model_validate_json(line)
        for line in lines[:2]
    )
    human_revisions = tuple(
        HumanRevisionRecord.model_validate_json(line) for line in lines[2:]
    )

    assert len(records) == 2
    assert all(
        record.record_type == "human_review_revision"
        for record in human_revisions
    )
    assert {record.base_question_id for record in records} == set(REVISED_QUESTIONS)
    assert all(record.human_approved is False for record in records)
    assert all(record.actor == "independent_reviewer_and_quality_audit" for record in records)
    assert all(record.trigger == "round_1_review_revision" for record in records)
    assert all(record.round1_inputs_hash == ROUND1_INPUTS_HASH for record in records)
    assert all(record.round1_reviews_hash == ROUND1_REVIEWS_HASH for record in records)
    assert all(record.prompt_version == ROUND1_PROMPT_VERSION for record in records)
    assert all(record.prompt_hash == ROUND1_PROMPT_HASH for record in records)
    assert set().union(*(set(record.affected_case_ids) for record in records)) == (
        REVISED_CASE_IDS
    )
    assert set().union(*(set(record.reviewer_revise_case_ids) for record in records)) == (
        ROUND1_REVISE_CASE_IDS
    )
    assert set().union(*(set(record.quality_audit_case_ids) for record in records)) == (
        QUALITY_AUDIT_CASE_IDS
    )
    assert all(record.after_question == REVISED_QUESTIONS[record.base_question_id]
               for record in records)
    for record in records:
        assert len(record.affected_case_ids) == 4
        assert len(record.reviewer_revise_case_ids) == 3
        assert len(record.quality_audit_case_ids) == 1


def test_rebuild_preserves_valid_human_revision_append_verbatim(
    fixture_data, tmp_path: Path,
) -> None:
    del fixture_data
    workspace = copy_fixture_workspace(tmp_path)
    change_log_path = workspace_fixture_path(workspace, CHANGE_LOG_PATH)
    record = HumanRevisionRecord.model_validate(human_revision_payload())
    appended = (
        canonical_json(record.model_dump(mode="json")) + "\n"
    ).encode("utf-8")
    expected = change_log_path.read_bytes() + appended
    change_log_path.write_bytes(expected)

    result = run_builder(workspace)

    assert result.returncode == 0, result.stderr
    assert change_log_path.read_bytes() == expected


def test_rebuild_preserves_concurrent_canonical_change_log_appends_verbatim(
    fixture_data, tmp_path: Path,
) -> None:
    del fixture_data
    workspace = copy_fixture_workspace(tmp_path)
    change_log_path = workspace_fixture_path(workspace, CHANGE_LOG_PATH)
    original = change_log_path.read_bytes()
    existing_test_record = HumanRevisionRecord.model_validate(
        human_revision_payload(case_id="case-existing-human-revision")
    ).model_dump(mode="json")
    concurrent_test_record = HumanRevisionRecord.model_validate(
        human_revision_payload(
            case_id="case-concurrent-human-revision",
            before_review_target_hash="c" * 64,
            after_review_target_hash="d" * 64,
        )
    ).model_dump(mode="json")
    existing = original + (
        canonical_json(existing_test_record) + "\n"
    ).encode("utf-8")
    concurrent = (canonical_json(concurrent_test_record) + "\n").encode("utf-8")
    change_log_path.write_bytes(existing)
    process = subprocess.Popen(
        builder_command(workspace),
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    with change_log_path.open("ab") as stream:
        stream.write(concurrent)
    stdout, stderr = process.communicate(timeout=60)
    assert process.returncode == 0, f"stdout={stdout}\nstderr={stderr}"
    assert change_log_path.read_bytes() == existing + concurrent


@pytest.mark.parametrize("damaged_state", ("empty", "missing"))
def test_rebuild_rejects_missing_or_empty_change_log_before_writing_outputs(
    fixture_data, tmp_path: Path, damaged_state: str,
) -> None:
    del fixture_data
    workspace = copy_fixture_workspace(tmp_path)
    change_log_path = workspace_fixture_path(workspace, CHANGE_LOG_PATH)
    drafts_path = workspace_fixture_path(workspace, DRAFTS_PATH)
    sentinel = b"test sentinel: damaged change log must fail before writes\n"
    if damaged_state == "empty":
        change_log_path.write_bytes(b"")
    else:
        change_log_path.unlink()
    drafts_path.write_bytes(sentinel)

    result = run_builder(workspace)

    assert result.returncode != 0
    assert "change_log.jsonl" in result.stderr
    if damaged_state == "empty":
        assert change_log_path.read_bytes() == b""
    else:
        assert not change_log_path.exists()
    assert drafts_path.read_bytes() == sentinel


def test_rebuild_rejects_tampered_round1_prompt_before_writing_outputs(
    fixture_data, tmp_path: Path,
) -> None:
    del fixture_data
    workspace = copy_fixture_workspace(tmp_path)
    prompt_path = workspace_fixture_path(workspace, REVIEWER_PROMPT_PATH)
    drafts_path = workspace_fixture_path(workspace, DRAFTS_PATH)
    original_prompt = prompt_path.read_bytes()
    tampered_prompt = original_prompt + b"\n"
    sentinel = b"test sentinel: prompt mismatch must fail before writes\n"
    prompt_path.write_bytes(tampered_prompt)
    drafts_path.write_bytes(sentinel)

    result = run_builder(workspace)

    assert result.returncode != 0
    assert "reviewer_prompt_v1.md" in result.stderr
    assert prompt_path.read_bytes() == tampered_prompt
    assert drafts_path.read_bytes() == sentinel


def test_rebuild_rejects_changed_change_log_prefix_before_writing_outputs(
    fixture_data, tmp_path: Path,
) -> None:
    del fixture_data
    workspace = copy_fixture_workspace(tmp_path)
    change_log_path = workspace_fixture_path(workspace, CHANGE_LOG_PATH)
    drafts_path = workspace_fixture_path(workspace, DRAFTS_PATH)
    original_log = change_log_path.read_bytes()
    tampered = original_log.replace(
        b'"independent_reviewer_and_quality_audit"',
        b'"xndependent_reviewer_and_quality_audit"',
        1,
    )
    assert tampered != original_log
    sentinel = b"test sentinel: builder must fail before writes\n"
    change_log_path.write_bytes(tampered)
    drafts_path.write_bytes(sentinel)

    result = run_builder(workspace)

    assert result.returncode != 0
    assert "change_log.jsonl" in result.stderr
    assert change_log_path.read_bytes() == tampered
    assert drafts_path.read_bytes() == sentinel


@pytest.mark.parametrize(
    "invalid_suffix",
    (
        b'[]\n',
        b'{ "test_only":true}\n',
        b'{"test_only":true}\r\n',
        b'{"test_only":true}',
    ),
)
def test_rebuild_rejects_invalid_change_log_append(
    fixture_data, tmp_path: Path, invalid_suffix: bytes,
) -> None:
    del fixture_data
    workspace = copy_fixture_workspace(tmp_path)
    change_log_path = workspace_fixture_path(workspace, CHANGE_LOG_PATH)
    original = change_log_path.read_bytes()
    invalid = original + invalid_suffix
    change_log_path.write_bytes(invalid)

    result = run_builder(workspace)

    assert result.returncode != 0
    assert "change_log.jsonl" in result.stderr
    assert change_log_path.read_bytes() == invalid


@pytest.mark.parametrize(
    "invalid_payload",
    (
        human_revision_payload(after_review_target_hash="a" * 64),
        human_revision_payload(changed_at="2026-09-25T10:00:00"),
        human_revision_payload(after_summary=""),
        human_revision_payload(after_summary="已修复"),
        {key: value for key, value in human_revision_payload().items()
         if key != "actor"},
        human_revision_payload(unexpected="not allowed"),
    ),
    ids=(
        "same-hash",
        "naive-changed-at",
        "blank-summary",
        "placeholder-summary",
        "missing-field",
        "extra-field",
    ),
)
def test_rebuild_rejects_invalid_human_revision_before_writing_outputs(
    fixture_data,
    tmp_path: Path,
    invalid_payload: dict[str, object],
) -> None:
    del fixture_data
    workspace = copy_fixture_workspace(tmp_path)
    change_log_path = workspace_fixture_path(workspace, CHANGE_LOG_PATH)
    drafts_path = workspace_fixture_path(workspace, DRAFTS_PATH)
    invalid = change_log_path.read_bytes() + (
        canonical_json(invalid_payload) + "\n"
    ).encode("utf-8")
    sentinel = b"test sentinel: invalid human revision must fail before writes\n"
    change_log_path.write_bytes(invalid)
    drafts_path.write_bytes(sentinel)

    result = run_builder(workspace)

    assert result.returncode != 0
    assert "change_log.jsonl" in result.stderr
    assert change_log_path.read_bytes() == invalid
    assert drafts_path.read_bytes() == sentinel


def test_rebuild_rejects_noncanonical_human_revision_before_writing_outputs(
    fixture_data, tmp_path: Path,
) -> None:
    del fixture_data
    workspace = copy_fixture_workspace(tmp_path)
    change_log_path = workspace_fixture_path(workspace, CHANGE_LOG_PATH)
    drafts_path = workspace_fixture_path(workspace, DRAFTS_PATH)
    noncanonical_line = json.dumps(
        human_revision_payload(), ensure_ascii=False, sort_keys=True
    ).encode("utf-8") + b"\n"
    invalid = change_log_path.read_bytes() + noncanonical_line
    sentinel = b"test sentinel: noncanonical human revision must fail before writes\n"
    change_log_path.write_bytes(invalid)
    drafts_path.write_bytes(sentinel)

    result = run_builder(workspace)

    assert result.returncode != 0
    assert "change_log.jsonl" in result.stderr
    assert change_log_path.read_bytes() == invalid
    assert drafts_path.read_bytes() == sentinel


def test_pending_fixture_review_can_apply_gate_then_freeze_without_rebinding(
    fixture_data, tmp_path: Path,
) -> None:
    _, chunks, claims, _, cases, environments = fixture_data
    case = next(item for item in cases if item.category is CaseCategory.LOCAL_SUFFICIENT)
    case = case.model_copy(update={
        "review_status": ReviewStatus.PENDING,
        "human_review_status": HumanReviewStatus.NOT_REQUIRED,
    })
    environment = next(
        item for item in environments if item.environment_id == case.environment_id
    )
    review = ReviewRecord(
        case_id=case.case_id,
        review_target_hash=compute_review_target_hash(case, environment, chunks, claims),
        decision=ReviewDecision.APPROVE,
        issues=(),
        suggested_changes=(),
        evidence_refs=(case.evidence_chunk_ids[0],),
        reviewer_confidence=0.9,
        labeler_reasoning_seen=False,
        prior_rule_failure_count=0,
        prompt_version="review-v1",
        prompt_hash="a" * 64,
        model_provider="provider",
        model_name="reviewer",
        model_revision="r1",
        reviewed_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )

    reviewed_case = apply_review_gate(case, environment, chunks, claims, review)

    assert reviewed_case.review_status is ReviewStatus.APPROVED
    assert reviewed_case.human_review_status is HumanReviewStatus.NOT_REQUIRED
    assert compute_review_target_hash(
        reviewed_case, environment, chunks, claims
    ) == review.review_target_hash
    result = freeze_benchmark(
        [(reviewed_case, environment)], [review], chunks, claims, tmp_path
    )
    assert result.case_count == 1
    assert result.runtime_path.is_file()


@pytest.mark.parametrize("category", [CaseCategory.OUTDATED, CaseCategory.CONFLICT])
def test_high_risk_review_may_cite_controlled_environment_chunk(
    fixture_data, tmp_path: Path, category: CaseCategory,
) -> None:
    _, chunks, claims, _, cases, environments = fixture_data
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    case = next(item for item in cases if item.category is category)
    case = case.model_copy(update={
        "review_status": ReviewStatus.PENDING,
        "human_review_status": HumanReviewStatus.NOT_REQUIRED,
    })
    environment = next(
        item for item in environments if item.environment_id == case.environment_id
    )
    environment_chunk_ids = (
        environment.visible_chunk_ids
        + environment.research_chunk_ids
        + environment.excluded_chunk_ids
    )
    controlled_chunk_id = next(
        chunk_id
        for chunk_id in environment_chunk_ids
        if chunks_by_id[chunk_id].source_id == "controlled-benchmark-distractors"
    )
    review = ReviewRecord(
        case_id=case.case_id,
        review_target_hash=compute_review_target_hash(case, environment, chunks, claims),
        decision=ReviewDecision.APPROVE,
        issues=(),
        suggested_changes=(),
        evidence_refs=(controlled_chunk_id,),
        reviewer_confidence=0.9,
        labeler_reasoning_seen=False,
        prior_rule_failure_count=0,
        prompt_version="review-v1",
        prompt_hash="a" * 64,
        model_provider="provider",
        model_name="reviewer",
        model_revision="r1",
        reviewed_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )

    reviewed_case = apply_review_gate(case, environment, chunks, claims, review)
    result = freeze_benchmark(
        [(reviewed_case, environment)],
        [review],
        chunks,
        claims,
        tmp_path,
        require_human_approval=False,
    )

    assert result.case_count == 1


@pytest.mark.parametrize("damage", ("partial", "extra", "stale"))
def test_rebuild_rejects_invalid_review_set_before_writing_outputs(
    tmp_path: Path, damage: str,
) -> None:
    workspace = copy_fixture_workspace(tmp_path)
    reviews_path = workspace_fixture_path(workspace, REVIEWS_PATH)
    drafts_path = workspace_fixture_path(workspace, DRAFTS_PATH)
    queue_path = workspace_fixture_path(workspace, HUMAN_REVIEW_QUEUE_PATH)
    original_reviews = reviews_path.read_bytes()
    rows = [json.loads(line) for line in original_reviews.decode("utf-8").splitlines()]
    if damage == "partial":
        rows = rows[:-1]
    elif damage == "extra":
        extra = dict(rows[0])
        extra["case_id"] = "case-extra-review"
        rows.append(extra)
    else:
        rows[0] = dict(rows[0])
        rows[0]["review_target_hash"] = "0" * 64
    invalid_reviews = "".join(f"{canonical_json(row)}\n" for row in rows).encode("utf-8")
    drafts_sentinel = b"test sentinel: invalid reviews must fail before writes\n"
    queue_sentinel = b"test sentinel: queue must not be overwritten\n"
    reviews_path.write_bytes(invalid_reviews)
    drafts_path.write_bytes(drafts_sentinel)
    queue_path.write_bytes(queue_sentinel)

    result = run_builder(workspace)

    assert result.returncode != 0
    assert reviews_path.read_bytes() == invalid_reviews
    assert drafts_path.read_bytes() == drafts_sentinel
    assert queue_path.read_bytes() == queue_sentinel


@pytest.mark.parametrize(
    "mutation",
    (
        "prompt_version",
        "prompt_hash",
        "model_provider",
        "model_name",
        "model_revision",
        "reviewed_at",
        "decision",
        "confidence",
        "evidence_refs",
        "order",
        "noncanonical",
    ),
)
def test_rebuild_rejects_reviews_different_from_archived_merge_before_writes(
    tmp_path: Path, mutation: str,
) -> None:
    workspace = copy_fixture_workspace(tmp_path)
    reviews_path = workspace_fixture_path(workspace, REVIEWS_PATH)
    drafts_path = workspace_fixture_path(workspace, DRAFTS_PATH)
    queue_path = workspace_fixture_path(workspace, HUMAN_REVIEW_QUEUE_PATH)
    review_inputs_path = workspace_fixture_path(workspace, REVIEW_INPUTS_PATH)
    original_reviews = reviews_path.read_bytes()
    rows = [json.loads(line) for line in original_reviews.decode("utf-8").splitlines()]
    inputs_by_case = {
        item.case.case_id: item
        for item in (
            ReviewInput.model_validate_json(line)
            for line in review_inputs_path.read_text(encoding="utf-8").splitlines()
        )
    }

    if mutation == "order":
        rows[0], rows[1] = rows[1], rows[0]
    elif mutation == "noncanonical":
        pass
    else:
        row = rows[0]
        if mutation == "prompt_version":
            row["prompt_version"] = "tampered-prompt-version"
        elif mutation == "prompt_hash":
            row["prompt_hash"] = "f" * 64
        elif mutation == "model_provider":
            row["model_provider"] = "tampered-provider"
        elif mutation == "model_name":
            row["model_name"] = "tampered-model"
        elif mutation == "model_revision":
            row["model_revision"] = "tampered-revision"
        elif mutation == "reviewed_at":
            row["reviewed_at"] = "2026-09-24T23:59:59+08:00"
        elif mutation == "decision":
            row["decision"] = "revise"
            row["issues"] = ["攻击回归中的合法修订理由"]
            row["suggested_changes"] = ["攻击回归中的合法修订建议"]
        elif mutation == "confidence":
            row["reviewer_confidence"] = 0.81
        else:
            review_input = inputs_by_case[row["case_id"]]
            environment_chunk_ids = tuple(
                chunk.chunk_id
                for chunk in (
                    review_input.environment.visible_chunks
                    + review_input.environment.research_chunks
                    + review_input.environment.excluded_chunks
                )
            )
            row["evidence_refs"] = [
                chunk_id
                for chunk_id in environment_chunk_ids
                if chunk_id not in row["evidence_refs"]
            ][:1]
            assert row["evidence_refs"]
        ReviewRecord.model_validate(row)

    invalid_reviews = "".join(
        f"{canonical_json(row)}\n" for row in rows
    ).encode("utf-8")
    if mutation == "noncanonical":
        invalid_reviews = invalid_reviews.replace(b'{"case_id"', b'{ "case_id"', 1)
    drafts_sentinel = b"test sentinel: archived merge mismatch must fail before writes\n"
    queue_sentinel = b"test sentinel: archived merge mismatch must preserve queue\n"
    reviews_path.write_bytes(invalid_reviews)
    drafts_path.write_bytes(drafts_sentinel)
    queue_path.write_bytes(queue_sentinel)

    result = run_builder(workspace)

    assert result.returncode != 0
    assert reviews_path.read_bytes() == invalid_reviews
    assert drafts_path.read_bytes() == drafts_sentinel
    assert queue_path.read_bytes() == queue_sentinel


def test_empty_reviews_keep_pending_drafts_and_empty_human_queue(
    tmp_path: Path,
) -> None:
    workspace = copy_fixture_workspace(tmp_path)
    reviews_path = workspace_fixture_path(workspace, REVIEWS_PATH)
    drafts_path = workspace_fixture_path(workspace, DRAFTS_PATH)
    queue_path = workspace_fixture_path(workspace, HUMAN_REVIEW_QUEUE_PATH)
    reviews_path.write_bytes(b"")

    result = run_builder(workspace)

    assert result.returncode == 0, result.stderr
    pending_cases = tuple(
        BenchmarkCase.model_validate(row["case"])
        for row in read_jsonl(drafts_path)
    )
    assert reviews_path.read_bytes() == b""
    assert all(case.review_status is ReviewStatus.PENDING for case in pending_cases)
    assert all(
        case.human_review_status is HumanReviewStatus.NOT_REQUIRED
        for case in pending_cases
    )
    assert queue_path.read_bytes() == b""


def test_jsonl_is_canonical_and_reviewer_outputs_are_separated(fixture_data) -> None:
    _, _, _, drafts, _, _ = fixture_data
    assert all(set(draft) == {"case", "environment"} for draft in drafts)
    for path in (
        DOCUMENTS_PATH,
        CHUNKS_PATH,
        CLAIMS_PATH,
        DRAFTS_PATH,
        REVIEW_INPUTS_PATH,
        REVIEWS_PATH,
        HUMAN_REVIEW_QUEUE_PATH,
        CHANGE_LOG_PATH,
        ROUND1_INPUTS_PATH,
        ROUND1_REVIEWS_PATH,
        ROUND2_INPUTS_PATH,
        ROUND2_REVIEWS_PATH,
    ):
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines
        assert all(line == canonical_json(json.loads(line)) for line in lines)
    assert len(REVIEWS_PATH.read_text(encoding="utf-8").splitlines()) == 48
    assert len(HUMAN_REVIEW_QUEUE_PATH.read_text(encoding="utf-8").splitlines()) == 24
    assert len(CHANGE_LOG_PATH.read_text(encoding="utf-8").splitlines()) >= 2
    assert not PROPOSED_REVIEWS_PATH.exists()
    assert not ROUND2_PROPOSED_REVIEWS_PATH.exists()


def test_rebuild_is_byte_identical_without_external_sources(
    fixture_data, tmp_path: Path,
) -> None:
    del fixture_data
    workspace = copy_fixture_workspace(tmp_path)
    generated = (
        MANIFEST_PATH,
        DOCUMENTS_PATH,
        CHUNKS_PATH,
        CLAIMS_PATH,
        DRAFTS_PATH,
        REVIEW_INPUTS_PATH,
        ROUND1_INPUTS_PATH,
        ROUND1_REVIEWS_PATH,
        ROUND2_INPUTS_PATH,
        ROUND2_REVIEWS_PATH,
        REVIEWS_PATH,
        HUMAN_REVIEW_QUEUE_PATH,
        CHANGE_LOG_PATH,
    )
    isolated_generated = tuple(
        workspace_fixture_path(workspace, path) for path in generated
    )
    before = {path: path.read_bytes() for path in isolated_generated}

    result = run_builder(workspace)

    assert result.returncode == 0, result.stderr
    assert {path: path.read_bytes() for path in isolated_generated} == before
