import json
import importlib.util
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from knowledge_gap_agent.benchmark.review import ReviewTargetInput
from knowledge_gap_agent.utils.canonical import sha256_hex


ROOT = Path(__file__).parents[2]
BENCHMARK_FIXTURES = ROOT / "fixtures" / "benchmark"
CORPUS_FIXTURES = ROOT / "fixtures" / "corpus"
CHECKLIST = ROOT / "docs" / "阶段一人工终审清单.md"
RENDERER = ROOT / "scripts" / "render_stage_01_human_review_checklist.py"
DECISIONS = ROOT / "docs" / "decisions.md"
AI_CODING_GUIDE = ROOT / "docs" / "AI_CODING_GUIDE.md"
BENCHMARK_CONSTRUCTION = ROOT / "docs" / "benchmark-construction.md"
EXPERIMENTS = ROOT / "docs" / "experiments.md"
TODO = ROOT / "docs" / "TODO.md"
PITFALLS = ROOT / "docs" / "pitfalls.md"


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def parse_named_json_blocks(text: str, marker: str) -> list[tuple[str, dict]]:
    pattern = re.compile(
        rf"(?ms)^<!-- {re.escape(marker)}:(?P<key>[^ ]+) -->\n"
        rf"```json\n(?P<body>.*?)\n```$"
    )
    return [
        (match["key"], json.loads(match["body"]))
        for match in pattern.finditer(text)
    ]


def index_unique(rows: list[dict], key: str) -> dict[str, dict]:
    result = {row[key]: row for row in rows}
    assert len(result) == len(rows)
    return result


def build_expected_cards_from_fixtures() -> dict[str, dict]:
    queue = index_unique(load_jsonl(BENCHMARK_FIXTURES / "human_review_queue.jsonl"), "case_id")
    input_rows = load_jsonl(BENCHMARK_FIXTURES / "review_inputs.jsonl")
    inputs = index_unique(
        [row | {"case_id": row["case"]["case_id"]} for row in input_rows],
        "case_id",
    )
    reviews = index_unique(load_jsonl(BENCHMARK_FIXTURES / "reviews.jsonl"), "case_id")
    drafts = index_unique(
        [row["case"] for row in load_jsonl(BENCHMARK_FIXTURES / "drafts.jsonl")],
        "case_id",
    )

    assert set(inputs) == set(reviews) == set(drafts)
    assert len(queue) == 24
    assert Counter(row["category"] for row in queue.values()) == {
        "outdated": 12,
        "conflict": 12,
    }

    result = {}
    for case_id, queued in queue.items():
        item = inputs[case_id]
        case = item["case"]
        environment = item["environment"]
        result[case_id] = {
            "case_id": case_id,
            "base_question_id": case["base_question_id"],
            "category": case["category"],
            "trigger": queued["trigger"],
            "review_target_hash": item["review_target_hash"],
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
            "draft_status": drafts[case_id]["draft_status"],
            "review_status": drafts[case_id]["review_status"],
            "human_review_status": drafts[case_id]["human_review_status"],
            "model_review": reviews[case_id],
            "human_decision": None,
            "human_reason": None,
            "requested_changes": [],
        }
    return result


def build_expected_evidence_from_fixtures(ids: set[str]) -> dict[str, dict]:
    chunks = index_unique(load_jsonl(CORPUS_FIXTURES / "chunks.jsonl"), "chunk_id")
    claims = index_unique(load_jsonl(CORPUS_FIXTURES / "claims.jsonl"), "claim_id")
    return {
        chunk_id: {
            **chunks[chunk_id],
            "claims": [claims[claim_id] for claim_id in chunks[chunk_id]["claim_ids"]],
        }
        for chunk_id in sorted(ids)
    }


def copy_renderer_inputs(destination: Path) -> None:
    benchmark = destination / "fixtures" / "benchmark"
    corpus = destination / "fixtures" / "corpus"
    benchmark.mkdir(parents=True)
    corpus.mkdir(parents=True)
    for name in ("drafts.jsonl", "human_review_queue.jsonl", "review_inputs.jsonl", "reviews.jsonl"):
        shutil.copyfile(BENCHMARK_FIXTURES / name, benchmark / name)
    for name in ("chunks.jsonl", "claims.jsonl"):
        shutil.copyfile(CORPUS_FIXTURES / name, corpus / name)


def run_renderer(workspace: Path, output: Path | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(RENDERER),
            "--workspace-root",
            str(workspace),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def rewrite_jsonl(path: Path, mutate) -> None:
    rows = load_jsonl(path)
    mutate(rows)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def assert_renderer_rejects_without_output_side_effect(workspace: Path) -> subprocess.CompletedProcess[str]:
    output = workspace / "existing.md"
    output.write_bytes(b"sentinel\n")
    result = run_renderer(workspace, output)
    assert result.returncode != 0
    assert output.read_bytes() == b"sentinel\n"
    assert not list(workspace.glob(".existing.md.*.tmp"))
    return result


def test_cards_equal_current_fixture_projection_once_and_in_stable_order() -> None:
    blocks = parse_named_json_blocks(CHECKLIST.read_text(encoding="utf-8"), "review-card")
    expected = build_expected_cards_from_fixtures()
    expected_order = sorted(
        expected,
        key=lambda case_id: (
            expected[case_id]["base_question_id"],
            expected[case_id]["category"],
            case_id,
        ),
    )

    assert [case_id for case_id, _ in blocks] == expected_order
    assert Counter(case_id for case_id, _ in blocks) == Counter(
        {case_id: 1 for case_id in expected}
    )
    assert dict(blocks) == expected


def test_evidence_directory_is_complete_exact_deduplicated_and_sorted() -> None:
    text = CHECKLIST.read_text(encoding="utf-8")
    cards = dict(parse_named_json_blocks(text, "review-card"))
    evidence_blocks = parse_named_json_blocks(text, "evidence-chunk")
    referenced = {
        chunk_id
        for card in cards.values()
        for field in ("visible_chunk_ids", "research_chunk_ids", "excluded_chunk_ids")
        for chunk_id in card[field]
    }

    assert [chunk_id for chunk_id, _ in evidence_blocks] == sorted(referenced)
    assert Counter(chunk_id for chunk_id, _ in evidence_blocks) == Counter(referenced)
    assert dict(evidence_blocks) == build_expected_evidence_from_fixtures(referenced)


def test_checklist_keeps_human_fields_empty_and_current_release_gate_closed() -> None:
    text = CHECKLIST.read_text(encoding="utf-8")
    cards = dict(parse_named_json_blocks(text, "review-card"))

    assert "模型 `approve` 不等于人工批准" in text
    assert "当前禁止正式 freeze 和创建阶段标签" in text
    assert len(cards) == 24
    assert Counter(card["category"] for card in cards.values()) == {
        "outdated": 12,
        "conflict": 12,
    }
    for card in cards.values():
        assert card["human_decision"] is None
        assert card["human_reason"] is None
        assert card["requested_changes"] == []
        assert card["human_review_status"] == "pending"

    # 当前阶段门禁：人工记录尚未产生，因此正式冻结文件和阶段标签都必须不存在。
    assert not (BENCHMARK_FIXTURES / "human_reviews.jsonl").exists()
    assert not list(BENCHMARK_FIXTURES.glob("benchmark-v0.1.*.jsonl"))
    tags = subprocess.run(
        ["git", "tag", "--list", "learn-v0.1-eval-contract"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert tags == ""


def test_renderer_recreates_identical_utf8_lf_bytes_for_relative_and_absolute_output(
    tmp_path: Path,
) -> None:
    copy_renderer_inputs(tmp_path)
    human_reviews = tmp_path / "fixtures" / "benchmark" / "human_reviews.jsonl"
    human_reviews.write_text("not renderer input", encoding="utf-8")

    relative = run_renderer(tmp_path, "out/checklist.md")
    absolute_path = tmp_path / "absolute.md"
    absolute = run_renderer(tmp_path, absolute_path)

    assert relative.returncode == 0, relative.stderr
    assert absolute.returncode == 0, absolute.stderr
    expected = CHECKLIST.read_bytes()
    assert (tmp_path / "out" / "checklist.md").read_bytes() == expected
    assert absolute_path.read_bytes() == expected
    assert b"\r\n" not in expected
    assert human_reviews.read_text(encoding="utf-8") == "not renderer input"


def test_renderer_rejects_inconsistent_case_sets_before_writing(tmp_path: Path) -> None:
    copy_renderer_inputs(tmp_path)
    queue_path = tmp_path / "fixtures" / "benchmark" / "human_review_queue.jsonl"
    queue_path.write_text(
        "\n".join(queue_path.read_text(encoding="utf-8").splitlines()[1:]) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    output = tmp_path / "must-not-exist.md"

    result = run_renderer(tmp_path, output)

    assert result.returncode != 0
    assert "24" in result.stderr or "24" in result.stdout
    assert not output.exists()


def test_renderer_rejects_missing_referenced_chunk_before_writing(tmp_path: Path) -> None:
    copy_renderer_inputs(tmp_path)
    chunks_path = tmp_path / "fixtures" / "corpus" / "chunks.jsonl"
    chunks_path.write_text(
        "\n".join(chunks_path.read_text(encoding="utf-8").splitlines()[1:]) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    output = tmp_path / "must-not-exist.md"

    result = run_renderer(tmp_path, output)

    assert result.returncode != 0
    assert "chunk" in result.stderr.lower() or "chunk" in result.stdout.lower()
    assert not output.exists()


def test_renderer_revalidates_archived_environment_hash(tmp_path: Path) -> None:
    copy_renderer_inputs(tmp_path)
    path = tmp_path / "fixtures" / "benchmark" / "drafts.jsonl"

    def tamper(rows: list[dict]) -> None:
        rows[0]["environment"]["environment_hash"] = "0" * 64

    rewrite_jsonl(path, tamper)

    result = assert_renderer_rejects_without_output_side_effect(tmp_path)
    assert "environment_hash" in result.stderr


def test_renderer_rebuilds_review_input_from_current_corpus(tmp_path: Path) -> None:
    copy_renderer_inputs(tmp_path)
    path = tmp_path / "fixtures" / "corpus" / "chunks.jsonl"

    def tamper(rows: list[dict]) -> None:
        rows[0]["text"] += " tampered"

    rewrite_jsonl(path, tamper)

    result = assert_renderer_rejects_without_output_side_effect(tmp_path)
    assert "content_hash" in result.stderr or "review input" in result.stderr


def test_renderer_revalidates_review_and_queue_models(tmp_path: Path) -> None:
    copy_renderer_inputs(tmp_path)
    reviews_path = tmp_path / "fixtures" / "benchmark" / "reviews.jsonl"
    queue_path = tmp_path / "fixtures" / "benchmark" / "human_review_queue.jsonl"
    queued_case_id = load_jsonl(queue_path)[0]["case_id"]

    def tamper_review(rows: list[dict]) -> None:
        next(row for row in rows if row["case_id"] == queued_case_id)["decision"] = "invalid"

    def tamper_queue(rows: list[dict]) -> None:
        next(row for row in rows if row["case_id"] == queued_case_id)["decision"] = "invalid"

    rewrite_jsonl(reviews_path, tamper_review)
    rewrite_jsonl(queue_path, tamper_queue)

    result = assert_renderer_rejects_without_output_side_effect(tmp_path)
    assert "decision" in result.stderr


@pytest.mark.parametrize(
    "tamper",
    ("environment_hash", "visible_chunk_text", "claim_statement"),
)
def test_renderer_rejects_self_consistent_archived_review_input_forgery(
    tmp_path: Path,
    tamper: str,
) -> None:
    copy_renderer_inputs(tmp_path)
    inputs_path = tmp_path / "fixtures" / "benchmark" / "review_inputs.jsonl"
    reviews_path = tmp_path / "fixtures" / "benchmark" / "reviews.jsonl"
    queue_path = tmp_path / "fixtures" / "benchmark" / "human_review_queue.jsonl"
    queued_case_id = load_jsonl(queue_path)[0]["case_id"]
    forged_hash = ""

    def tamper_input(rows: list[dict]) -> None:
        nonlocal forged_hash
        row = next(item for item in rows if item["case"]["case_id"] == queued_case_id)
        if tamper == "environment_hash":
            row["environment"]["environment_hash"] = "0" * 64
        elif tamper == "visible_chunk_text":
            row["environment"]["visible_chunks"][0]["text"] += " forged"
        else:
            row["claims"][0]["statement"] += " forged"
        target = ReviewTargetInput.model_validate(
            {key: value for key, value in row.items() if key != "review_target_hash"}
        )
        forged_hash = sha256_hex(target.model_dump(mode="json"))
        row["review_target_hash"] = forged_hash

    rewrite_jsonl(inputs_path, tamper_input)
    assert forged_hash

    def sync_hash(rows: list[dict]) -> None:
        next(row for row in rows if row["case_id"] == queued_case_id)[
            "review_target_hash"
        ] = forged_hash

    rewrite_jsonl(reviews_path, sync_hash)
    rewrite_jsonl(queue_path, sync_hash)

    result = assert_renderer_rejects_without_output_side_effect(tmp_path)
    assert "归档 review input 与当前 draft/environment/corpus 不一致" in result.stderr


def test_renderer_rejects_missing_claim_and_duplicate_corpus_ids(tmp_path: Path) -> None:
    for fault in ("missing_claim", "duplicate_chunk", "duplicate_claim"):
        workspace = tmp_path / fault
        copy_renderer_inputs(workspace)
        chunks_path = workspace / "fixtures" / "corpus" / "chunks.jsonl"
        claims_path = workspace / "fixtures" / "corpus" / "claims.jsonl"
        chunks = load_jsonl(chunks_path)
        claims = load_jsonl(claims_path)
        if fault == "missing_claim":
            referenced_claim = chunks[0]["claim_ids"][0]
            claims = [row for row in claims if row["claim_id"] != referenced_claim]
            claims_path.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in claims),
                encoding="utf-8",
                newline="\n",
            )
        elif fault == "duplicate_chunk":
            with chunks_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(chunks[0], ensure_ascii=False) + "\n")
        else:
            with claims_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(claims[0], ensure_ascii=False) + "\n")

        assert_renderer_rejects_without_output_side_effect(workspace)


def test_atomic_writer_cleans_temporary_file_and_preserves_existing_output(
    tmp_path: Path, monkeypatch
) -> None:
    spec = importlib.util.spec_from_file_location("checklist_renderer", RENDERER)
    assert spec is not None and spec.loader is not None
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    output = tmp_path / "checklist.md"
    output.write_bytes(b"sentinel\n")

    def fail_replace(*_args) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(renderer.os, "replace", fail_replace)

    try:
        renderer.write_output_atomic(output, "replacement\n")
    except OSError as error:
        assert str(error) == "injected replace failure"
    else:
        raise AssertionError("replace failure must escape")
    assert output.read_bytes() == b"sentinel\n"
    assert not list(tmp_path.glob(".checklist.md.*.tmp"))


def test_decisions_record_trusted_human_gate_contract() -> None:
    text = DECISIONS.read_text(encoding="utf-8")

    for term in (
        "HumanReviewRecord",
        "review_target_hash",
        "派生缓存",
        "精确相等",
        "候选冻结",
    ):
        assert term in text
    assert "model_copy" in text


def test_ai_coding_guide_records_safe_continuation_workflow() -> None:
    text = AI_CODING_GUIDE.read_text(encoding="utf-8")

    for term in (
        "--workspace-root",
        "HumanReviewRecord",
        "HumanRevisionRecord",
        "model_copy",
        "规格审查",
        "代码质量审查",
        "正式冻结",
        "阶段标签",
    ):
        assert term in text
    assert "不得自动生成真人结论" in text
    assert "不得让破坏性测试写入版本化 `fixtures/`" in text


def test_benchmark_construction_records_strict_semantics_and_review_artifacts() -> None:
    text = BENCHMARK_CONSTRUCTION.read_text(encoding="utf-8")

    for term in (
        "old.valid_until < current.valid_from",
        "HumanReviewRecord",
        "HumanRevisionRecord",
        "--workspace-root <path>",
        "render_stage_01_human_review_checklist.py",
        "47 个去重证据块",
    ):
        assert term in text
    assert "12 条 `outdated`" in text
    assert "12 条 `conflict`" in text


def test_pitfalls_only_record_two_reproduced_engineering_failures() -> None:
    text = PITFALLS.read_text(encoding="utf-8")
    issues = re.findall(r"(?m)^## (.+)$", text)

    assert len(issues) == 2
    assert any("夹具" in issue and "污染" in issue for issue in issues)
    assert any("人工门禁" in issue and "绕过" in issue for issue in issues)
    for subsection in ("复现条件", "影响", "根因", "回归测试", "禁止做法"):
        assert text.count(f"### {subsection}") == 2


def test_todo_keeps_day2_and_real_human_review_open() -> None:
    text = TODO.read_text(encoding="utf-8")

    assert re.search(r"(?m)^- \[ \] 第 1–2 天：", text)
    assert re.search(r"(?m)^  - \[ \] 第 2 天：", text)
    assert re.search(
        r"(?m)^    - \[ \] .*12 条 `outdated`.*12 条 `conflict`", text
    )
    assert re.search(r"(?m)^    - \[x\] 完成可信人工门禁工程修复", text)
    assert re.search(r"(?m)^    - \[x\] 已交付\[阶段一人工终审清单\]", text)


def test_experiment_record_uses_current_command_and_keeps_gate_pending() -> None:
    text = EXPERIMENTS.read_text(encoding="utf-8")

    assert "uv run python -m pytest -q" in text
    assert "2026-09-25" in text
    assert re.search(r"全量测试[^\n]*`\d+ passed, \d+ skipped`", text)
    assert "24 条高风险候选仍为人工 `pending`" in text
