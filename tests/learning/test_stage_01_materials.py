import ast
import importlib
import inspect
import json
import re
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from knowledge_gap_agent.retrieval.bm25 import BM25Index


ROOT = Path(__file__).parents[2]
STAGE = ROOT / "learning" / "stage-01-eval-contract"
MATERIALS = {
    name: STAGE / name
    for name in ("GUIDE.md", "LAB.md", "EXERCISES.md", "SOLUTIONS.md")
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def headings(text: str, level: int) -> list[str]:
    marker = "#" * level
    return re.findall(rf"(?m)^{marker} (.+)$", text)


def question_contract(text: str) -> dict[int, tuple[str, str]]:
    pattern = re.compile(
        r"(?m)^## 题(?P<number>[1-8])："
        r"(?P<kind>简答题|伪代码题|Trace 分析题|实验设计题|代码修改题)"
        r"（(?P<difficulty>基础|应用|挑战)）$"
    )
    return {
        int(match["number"]): (match["kind"], match["difficulty"])
        for match in pattern.finditer(text)
    }


def solution_blocks(text: str) -> dict[int, str]:
    matches = list(re.finditer(r"(?m)^## 题([1-8])$", text))
    return {
        int(match.group(1)): text[
            match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(text)
        ]
        for index, match in enumerate(matches)
    }


def exercise_blocks(text: str) -> dict[int, str]:
    matches = list(re.finditer(r"(?m)^## 题([1-8])：.*$", text))
    return {
        int(match.group(1)): text[
            match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(text)
        ]
        for index, match in enumerate(matches)
    }


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in read(path).splitlines()]


def test_stage_one_has_all_four_material_files() -> None:
    assert all(path.is_file() for path in MATERIALS.values())


def test_exercises_have_exact_required_type_distribution() -> None:
    exercises = read(MATERIALS["EXERCISES.md"])
    questions = question_contract(exercises)

    assert re.findall(r"(?m)^## 题([1-8])：", exercises) == list("12345678")
    assert set(questions) == set(range(1, 9))
    assert Counter(kind for kind, _ in questions.values()) == {
        "简答题": 3,
        "伪代码题": 2,
        "Trace 分析题": 1,
        "实验设计题": 1,
        "代码修改题": 1,
    }


def test_pseudocode_and_code_exercises_state_executable_contracts() -> None:
    exercises = read(MATERIALS["EXERCISES.md"])
    questions = question_contract(exercises)
    matches = list(re.finditer(r"(?m)^## 题[1-8]：.*$", exercises))
    blocks = {
        number: exercises[
            matches[number - 1].end() : matches[number].start() if number < 8 else len(exercises)
        ]
        for number in range(1, 9)
    }

    for number, (kind, _) in questions.items():
        if kind == "伪代码题":
            assert all(label in blocks[number] for label in ("输入：", "输出：", "约束：", "边界案例："))
        if kind == "代码修改题":
            assert "测试或断言：" in blocks[number]


def test_solutions_match_questions_and_have_four_required_sections() -> None:
    questions = question_contract(read(MATERIALS["EXERCISES.md"]))
    solution_text = read(MATERIALS["SOLUTIONS.md"])
    solutions = solution_blocks(solution_text)

    assert re.findall(r"(?m)^## 题([1-8])$", solution_text) == list("12345678")
    assert set(solutions) == set(questions)
    for block in solutions.values():
        assert all(
            heading in headings(block, 3)
            for heading in ("提示", "参考答案", "评分点", "常见错误")
        )
        scoring = block.split("### 评分点", 1)[1].split("### 常见错误", 1)[0]
        assert re.search(r"(?m)^- .+", scoring)


def test_question_eight_reference_test_imports_demo_locally_before_use() -> None:
    question_eight = solution_blocks(read(MATERIALS["SOLUTIONS.md"]))[8]
    python_blocks = re.findall(r"```python\n(.*?)```", question_eight, flags=re.DOTALL)
    reference_test = next(
        block for block in python_blocks
        if "test_build_payload_accepts_top_k_without_changing_default_contract" in block
    )
    tree = ast.parse(reference_test)

    assert any(
        isinstance(node, ast.Import)
        and any(alias.name == "importlib" for alias in node.names)
        for node in tree.body
    ), "题8参考测试必须显式导入 importlib"

    test_function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_build_payload_accepts_top_k_without_changing_default_contract"
    )
    demo_assignments = [
        node for node in ast.walk(test_function)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "demo" for target in node.targets)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and isinstance(node.value.func.value, ast.Name)
        and node.value.func.value.id == "importlib"
        and node.value.func.attr == "import_module"
        and len(node.value.args) == 1
        and isinstance(node.value.args[0], ast.Constant)
        and node.value.args[0].value == "demo.02_bm25_retrieval"
    ]
    demo_calls = [
        node for node in ast.walk(test_function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "demo"
        and node.func.attr == "build_payload"
    ]

    assert demo_assignments, "题8参考测试必须在测试函数内加载 demo 模块"
    assert demo_calls, "题8参考测试必须调用 demo.build_payload"
    assert demo_assignments[0].lineno < min(call.lineno for call in demo_calls)

    default_hash_assignments = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "EXPECTED_DEFAULT_RESULT_HASH"
            for target in node.targets
        )
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ]
    assert default_hash_assignments, "题8参考测试必须固定当前默认 payload 的 result_hash"
    documented_hash = default_hash_assignments[0].value.value
    assert re.fullmatch(r"[0-9a-f]{64}", documented_hash)
    current_demo = importlib.import_module("demo.02_bm25_retrieval")
    assert documented_hash == current_demo.build_payload()["result_hash"]
    assert "sha256_hex(unhashed)" in reference_test


def test_guide_sha256_wording_and_bm25_canary_match_real_implementation() -> None:
    guide = read(MATERIALS["GUIDE.md"])
    index = BM25Index.build([
        SimpleNamespace(chunk_id="a", text="apple apple banana"),
        SimpleNamespace(chunk_id="b", text="apple carrot carrot"),
    ])

    result = index.search("apple banana", top_k=2)[0]

    assert result.chunk_id == "a"
    assert result.score == pytest.approx(0.9536065474084518)
    assert result.score == pytest.approx(sum(result.term_scores.values()))
    assert "0.9536065474" in guide
    assert "\\operatorname{idf}" in guide
    assert "\\operatorname{score}" in guide
    assert "256 位摘要，以 64 个小写十六进制字符表示" in guide
    assert not re.search(r"64\s*位[^。\n|]*摘要", guide)


def test_top_k_lab_canary_changes_only_cutoff_and_matches_documentation() -> None:
    demo = importlib.import_module("demo.02_bm25_retrieval")
    query = "BM25 如何解释检索分数 人工终审 二元字组"
    index = BM25Index.build(demo.CHUNKS, k1=1.5, b=0.75)

    def observe(top_k: int) -> tuple[list, list[str], list[str]]:
        results = index.search(query, top_k=top_k)
        returned = {result.chunk_id for result in results}
        hits = sorted({
            claim_id
            for chunk in demo.CHUNKS
            if chunk.chunk_id in returned
            for claim_id in chunk.claim_ids
            if claim_id in demo.REQUIRED_CLAIM_IDS
        })
        missing = sorted(set(demo.REQUIRED_CLAIM_IDS) - set(hits))
        return results, hits, missing

    two, two_hits, two_missing = observe(2)
    three, three_hits, three_missing = observe(3)

    assert [result.chunk_id for result in two] == ["chunk-token", "chunk-formula"]
    assert [result.chunk_id for result in three] == [
        "chunk-token", "chunk-formula", "chunk-human-review"
    ]
    assert two_hits == ["claim-formula"]
    assert two_missing == ["claim-human-review"]
    assert three_hits == ["claim-formula", "claim-human-review"]
    assert three_missing == []
    assert {
        result.chunk_id: result.term_scores for result in two
    } == {
        result.chunk_id: result.term_scores for result in three[:2]
    }

    lab = read(MATERIALS["LAB.md"])
    question_seven = exercise_blocks(read(MATERIALS["EXERCISES.md"]))[7]
    answer_seven = solution_blocks(read(MATERIALS["SOLUTIONS.md"]))[7]
    for text in (lab, question_seven, answer_seven):
        assert query in text
        assert "chunk-token" in text
        assert "chunk-formula" in text
        assert "chunk-human-review" in text
        assert "claim-human-review" in text


def test_question_six_is_a_multi_event_trace_analysis_contract() -> None:
    question_six = exercise_blocks(read(MATERIALS["EXERCISES.md"]))[6]
    answer_six = solution_blocks(read(MATERIALS["SOLUTIONS.md"]))[6]

    assert all(
        field in question_six for field in ("step", "event_type", "status", "error_type")
    )
    assert len(re.findall(r"\bevent_type\s*[:=]", question_six)) >= 2
    assert all(
        event in question_six
        for event in ("run_started", "action_selected", "tool_completed", "run_finished")
    )
    assert all(
        boundary in answer_six
        for boundary in ("首个失败", "单条事件契约", "跨事件语义", "Runtime", "TraceStore")
    )
    assert "error_type" in answer_six and "构造" in answer_six and "拒绝" in answer_six


def test_question_five_uses_real_review_target_shape_and_preserves_human_terminal_state() -> None:
    answer_five = solution_blocks(read(MATERIALS["SOLUTIONS.md"]))[5]

    assert all(
        expression in answer_five
        for expression in (
            "target.environment.visible_chunks",
            "target.environment.research_chunks",
            "target.environment.excluded_chunks",
            "chunk.chunk_id",
            "HumanReviewStatus.APPROVED",
            "HumanReviewStatus.REJECTED",
        )
    )
    assert "人工终态" in answer_five


def test_candidate_fixture_status_is_read_from_real_files() -> None:
    fixture_dir = ROOT / "fixtures" / "benchmark"
    drafts = read_jsonl(fixture_dir / "drafts.jsonl")
    reviews = read_jsonl(fixture_dir / "reviews.jsonl")
    queue = read_jsonl(fixture_dir / "human_review_queue.jsonl")

    assert len(drafts) == len(reviews) == 48
    assert Counter(review["decision"] for review in reviews) == {"approve": 48}
    assert Counter(row["case"]["human_review_status"] for row in drafts) == {
        "not_required": 24,
        "pending": 24,
    }
    assert len(queue) == 24
    assert Counter(row["category"] for row in queue) == {
        "outdated": 12,
        "conflict": 12,
    }
    assert not list(fixture_dir.glob("benchmark-v0.1.*.jsonl"))


def test_documented_symbols_exist_and_lab_names_real_environment_validator() -> None:
    guide = read(MATERIALS["GUIDE.md"])
    lab = read(MATERIALS["LAB.md"])
    documentation = f"{guide}\n{lab}"
    symbols = (
        ("knowledge_gap_agent.utils.canonical", "canonical_json"),
        ("knowledge_gap_agent.utils.canonical", "sha256_hex"),
        ("knowledge_gap_agent.corpus.chunking", "chunk_markdown"),
        ("knowledge_gap_agent.retrieval.tokenizer", "tokenize"),
        ("knowledge_gap_agent.benchmark.validation", "validate_case"),
        ("knowledge_gap_agent.benchmark.validation", "build_runtime_payload"),
        ("knowledge_gap_agent.benchmark.validation", "build_model_input_payload"),
        ("knowledge_gap_agent.benchmark.review", "build_review_input"),
        ("knowledge_gap_agent.benchmark.review", "apply_review_gate"),
        ("knowledge_gap_agent.benchmark.freeze", "freeze_benchmark"),
    )
    for module_name, symbol_name in symbols:
        module = importlib.import_module(module_name)
        assert hasattr(module, symbol_name)
        assert callable(getattr(module, symbol_name))
        assert symbol_name in documentation

    models = importlib.import_module("knowledge_gap_agent.benchmark.models")
    validator = inspect.getattr_static(
        models.KnowledgeEnvironment, "validate_disjoint_sets_and_hash"
    )
    assert validator is not None
    assert "KnowledgeEnvironment.validate_disjoint_sets_and_hash" in lab
    assert "KnowledgeEnvironment.model_validator" not in lab


def test_guide_and_lab_cover_stage_one_contract() -> None:
    guide = read(MATERIALS["GUIDE.md"])
    lab = read(MATERIALS["LAB.md"])

    guide_topics = (
        "真实失败案例",
        "可以运行和观察什么",
        "输入、输出、依赖和非职责",
        "规范 JSON 与 SHA-256",
        "Markdown 行级切块",
        "BM25",
        "12×4 环境视图",
        "运行信封与模型输入白名单",
        "独立复核与人工升级",
        "成功链",
        "失败与早拒绝链",
        "代码与测试导航",
        "取舍与下一阶段边界",
        "验收命令",
    )
    assert all(topic in guide for topic in guide_topics)
    assert "3f92ae5a2e6bae78bb54759fdacc18f81d8d5960" in guide
    assert "ReviewInput" in guide and "ReviewRecord" in guide
    assert "review_target_hash" in guide
    assert "24" in guide and "pending" in guide

    assert all(
        heading in lab
        for heading in ("基础实验", "单变量参数实验", "故障实验", "统一记录模板")
    )
    assert "term_scores" in lab and "hit_claim_ids" in lab
    assert "外部 API key" in lab
    assert all(
        label in lab
        for label in (
            "实验假设：",
            "修改变量：",
            "控制变量：",
            "预期现象：",
            "实际结果：",
            "Trace 位置：",
            "结论：",
        )
    )


def test_documented_demos_and_source_paths_exist() -> None:
    guide = read(MATERIALS["GUIDE.md"])
    lab = read(MATERIALS["LAB.md"])
    referenced = (
        "demo/01_config_trace.py",
        "demo/02_bm25_retrieval.py",
        "src/knowledge_gap_agent/utils/canonical.py",
        "src/knowledge_gap_agent/corpus/chunking.py",
        "src/knowledge_gap_agent/retrieval/tokenizer.py",
        "src/knowledge_gap_agent/retrieval/bm25.py",
        "src/knowledge_gap_agent/benchmark/validation.py",
        "src/knowledge_gap_agent/benchmark/review.py",
        "src/knowledge_gap_agent/benchmark/freeze.py",
        "tests/retrieval/test_bm25.py",
        "tests/benchmark/test_review.py",
        "tests/benchmark/test_fixture_dataset.py",
    )
    for relative in referenced:
        assert relative in guide or relative in lab
        assert (ROOT / relative).is_file()


def test_materials_do_not_claim_human_approval_or_formal_freeze() -> None:
    status_documents = [
        *MATERIALS.values(),
        ROOT / "learning" / "README.md",
        ROOT / "docs" / "实验合同.md",
    ]
    corpus = "\n".join(read(path) for path in status_documents)

    assert "当前已获人工批准" not in corpus
    assert "human_review_status=approved" not in corpus
    assert "human approved" not in corpus.lower()
    assert "人工审核已通过" not in corpus
    assert "已正式冻结" not in corpus
    assert "正式基准已完成" not in corpus
    assert "正式冻结尚未完成" in corpus
    assert "24 条人工 `pending`" in corpus


def test_internal_markdown_links_resolve() -> None:
    documents = [ROOT / "learning" / "README.md", *MATERIALS.values()]
    link_pattern = re.compile(r"(?<!!)\[[^]]+]\(([^)]+)\)")
    local_links = []
    for document in documents:
        for raw_target in link_pattern.findall(read(document)):
            target = raw_target.split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            local_links.append((document, target))
            assert (document.parent / target).resolve().exists(), (
                f"{document.relative_to(ROOT)} contains broken link: {raw_target}"
            )
    assert local_links


def test_learning_readme_has_stage_one_entry_and_three_round_ai_prompts() -> None:
    readme = read(ROOT / "learning" / "README.md")

    assert "stage-01-eval-contract/GUIDE.md" in readme
    assert all(label in readme for label in ("第一轮：诊断", "第二轮：提示", "第三轮：评分"))
    assert "SOLUTIONS.md" in readme
    assert "不要虚构没有运行过的测试结果" in readme
