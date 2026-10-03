import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from knowledge_gap_agent.benchmark.review import ReviewInput
from knowledge_gap_agent.utils.canonical import canonical_json


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/build_day2_fixtures.py"


def tree_bytes(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def copy_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    shutil.copytree(ROOT / "fixtures", workspace / "fixtures")
    return workspace


def load_builder():
    spec = importlib.util.spec_from_file_location("revision_fixture_builder", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def preserve_real_fixtures():
    before = tree_bytes(ROOT / "fixtures")
    yield
    assert tree_bytes(ROOT / "fixtures") == before


def test_prepare_exports_only_changed_inputs_without_touching_fixtures(tmp_path):
    workspace = copy_workspace(tmp_path)
    output = tmp_path / "round-3-inputs.jsonl"
    before = tree_bytes(workspace)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--workspace-root",
            str(workspace),
            "--prepare-round3-output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert tree_bytes(workspace) == before
    baseline = {}
    for round_number in (1, 2):
        for line in (
            (
                workspace
                / f"fixtures/benchmark/review_history/round-{round_number}-inputs.jsonl"
            )
            .read_text(encoding="utf-8")
            .splitlines()
        ):
            item = ReviewInput.model_validate_json(line)
            baseline[item.case.case_id] = item
    rows = [
        ReviewInput.model_validate_json(line)
        for line in output.read_text(encoding="utf-8").splitlines()
    ]
    assert rows
    assert [r.case.case_id for r in rows] == sorted(r.case.case_id for r in rows)
    assert all(
        r.review_target_hash != baseline[r.case.case_id].review_target_hash
        for r in rows
    )
    module = load_builder()
    *_, current = module._construct_current_dataset(workspace)
    expected_changed = {
        key
        for key in current
        if current[key].review_target_hash != baseline[key].review_target_hash
    }
    assert {r.case.case_id for r in rows} == expected_changed
    assert {"base-01", "base-02"} <= {r.case.base_question_id for r in rows}
    assert not (workspace / "fixtures/benchmark/human_reviews.jsonl").exists()


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "duplicate",
        "stale",
        "actor",
        "decision",
        "noncanonical",
        "extra",
        "reason",
        "time",
        "changes",
    ],
)
def test_prepare_rejects_invalid_human_history_before_writing(
    tmp_path, monkeypatch, damage
):
    module = load_builder()
    workspace = copy_workspace(tmp_path)
    path = workspace / "fixtures/benchmark/human_review_history/round-1-reviews.jsonl"
    assert path.exists(), "必须先保存四条真实人工历史"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if damage == "missing":
        rows.pop()
    elif damage == "duplicate":
        rows.append(rows[0])
    elif damage == "stale":
        rows[0]["review_target_hash"] = "0" * 64
    elif damage == "actor":
        rows[0]["actor"] = "another-actor"
    elif damage == "decision":
        rows[0]["decision"] = "approved"
    elif damage == "extra":
        rows[0]["case_id"] = "case-extra"
    elif damage == "reason":
        rows[0]["reason"] = "被改写的人工理由"
    elif damage == "time":
        rows[0]["reviewed_at"] = "2026-10-03T01:00:00+08:00"
    elif damage == "changes":
        rows[0]["requested_changes"] = ["被改写的修改要求"]
    content = "".join(canonical_json(row) + "\n" for row in rows)
    if damage == "noncanonical":
        content = " " + content
    path.write_text(content, encoding="utf-8", newline="\n")
    if damage not in {"reason", "time", "changes"}:
        monkeypatch.setattr(
            module, "HUMAN_REVIEWS_HASH", hashlib.sha256(path.read_bytes()).hexdigest()
        )
    before = tree_bytes(workspace)
    output = tmp_path / "output.jsonl"
    with pytest.raises(ValueError):
        module.prepare_round3_review_inputs(workspace, output)
    assert not output.exists()
    assert tree_bytes(workspace) == before


@pytest.mark.parametrize(
    "destination", ["fixtures", "exists", "repository", "other_checkout"]
)
def test_prepare_rejects_unsafe_destination(tmp_path, destination):
    module = load_builder()
    workspace = copy_workspace(tmp_path)
    output = tmp_path / "output.jsonl"
    if destination == "fixtures":
        output = workspace / "fixtures/output.jsonl"
    elif destination == "exists":
        output.write_bytes(b"existing")
    elif destination == "repository":
        workspace = ROOT
    else:
        checkout = tmp_path / "fake-checkout"
        checkout.mkdir()
        (checkout / ".git").write_text("gitdir: unrelated", encoding="utf-8")
        output = checkout / "fixtures/new.jsonl"
    before = tree_bytes(workspace / "fixtures")
    with pytest.raises(ValueError):
        module.prepare_round3_review_inputs(workspace, output)
    assert tree_bytes(workspace / "fixtures") == before


def test_prepare_rejects_damaged_old_log_prefix(tmp_path):
    module = load_builder()
    workspace = copy_workspace(tmp_path)
    path = workspace / "fixtures/benchmark/change_log.jsonl"
    path.write_bytes(b" " + path.read_bytes())
    with pytest.raises(ValueError, match="前缀"):
        module.prepare_round3_review_inputs(workspace, tmp_path / "out.jsonl")


def test_prepare_allows_temp_boundary_below_unrelated_ancestor_checkout(
    tmp_path, monkeypatch
):
    module = load_builder()
    (tmp_path / ".git").mkdir()
    temporary_root = tmp_path / "system-temp"
    temporary_root.mkdir()
    monkeypatch.setattr(module.tempfile, "gettempdir", lambda: str(temporary_root))
    workspace = copy_workspace(temporary_root)
    output = temporary_root / "out.jsonl"
    assert module.prepare_round3_review_inputs(workspace, output)
    assert output.is_file()


def stage_synthetic_round3(tmp_path, monkeypatch):
    """合成结果仅限临时树，用来验证门禁，绝不作为真实复核。"""
    module = load_builder()
    workspace = copy_workspace(tmp_path)
    inputs = module.prepare_round3_review_inputs(workspace, tmp_path / "prepared.jsonl")
    baseline, first, second = module._load_pre_human_history(workspace)
    benchmark = workspace / "fixtures/benchmark"
    history = benchmark / "review_history"
    previous = {r.case_id: r for r in first + second}
    reviews = []
    revisions = []
    for item in inputs:
        review = previous[item.case.case_id].model_dump(mode="json")
        review.update(
            review_target_hash=item.review_target_hash,
            decision="approve",
            issues=[],
            suggested_changes=[],
            evidence_refs=[item.environment.research_chunks[0].chunk_id],
            reviewer_confidence=0.9,
            prompt_version="day2-benchmark-human-revision-rereview-v1",
            prompt_hash=hashlib.sha256(
                (benchmark / "reviewer_human_revision_prompt_v1.md").read_bytes()
            ).hexdigest(),
        )
        reviews.append(review)
        revisions.append(
            dict(
                schema_version="1.0",
                record_type="human_review_revision",
                case_id=item.case.case_id,
                actor="codex-implementation-agent",
                reason="四条项目所有者退回触发共享目标修订。",
                before_review_target_hash=baseline[
                    item.case.case_id
                ].review_target_hash,
                after_review_target_hash=item.review_target_hash,
                before_summary="旧问题、容器主张或受控正文未明确裁决依据。",
                after_summary="问题和证据更新为规范化边界、tuple 选择及编码规则。",
                changed_at="2026-10-03T15:30:00+08:00",
            )
        )
    log = benchmark / "change_log.jsonl"
    log.write_bytes(
        log.read_bytes()[:2585] + module._canonical_jsonl_bytes(tuple(revisions))
    )
    (history / "round-3-inputs.jsonl").write_bytes(
        (tmp_path / "prepared.jsonl").read_bytes()
    )
    (history / "round-3-reviews.jsonl").write_bytes(
        module._canonical_jsonl_bytes(tuple(reviews))
    )
    (history / "round-3-reviews.raw.jsonl").write_bytes(
        module._canonical_jsonl_bytes(tuple(reviews))
    )
    for constant, path in (
        ("ROUND3_INPUTS_HASH", history / "round-3-inputs.jsonl"),
        ("ROUND3_REVIEWS_HASH", history / "round-3-reviews.jsonl"),
        ("ROUND3_RAW_REVIEWS_HASH", history / "round-3-reviews.raw.jsonl"),
        ("ROUND3_PROMPT_HASH", benchmark / "reviewer_human_revision_prompt_v1.md"),
    ):
        monkeypatch.setattr(
            module,
            constant,
            hashlib.sha256(path.read_bytes()).hexdigest(),
            raising=False,
        )
    merged = {r.case_id: r.model_dump(mode="json") for r in first + second}
    merged.update({r["case_id"]: r for r in reviews})
    (benchmark / "reviews.jsonl").write_bytes(
        module._canonical_jsonl_bytes(tuple(merged[k] for k in sorted(merged)))
    )
    return module, workspace, inputs


def test_formal_build_requires_real_round3_before_writes(tmp_path):
    module = load_builder()
    workspace = copy_workspace(tmp_path)
    (workspace / "fixtures/benchmark/review_history/round-3-reviews.jsonl").unlink(
        missing_ok=True
    )
    before = tree_bytes(workspace)
    with pytest.raises((ValueError, FileNotFoundError), match="第三轮|修订日志"):
        module.build(workspace)
    assert tree_bytes(workspace) == before


@pytest.mark.parametrize("state", ["missing", "empty"])
def test_formal_build_requires_nonempty_current_merged_reviews(tmp_path, state):
    module = load_builder()
    workspace = copy_workspace(tmp_path)
    path = workspace / "fixtures/benchmark/reviews.jsonl"
    if state == "missing":
        path.unlink()
    else:
        path.write_bytes(b"")
    before = tree_bytes(workspace)
    with pytest.raises(ValueError, match="reviews.jsonl.*非空"):
        module.build(workspace)
    assert tree_bytes(workspace) == before


def test_invalid_revision_reports_file_and_line_with_original_cause(tmp_path):
    module = load_builder()
    workspace = copy_workspace(tmp_path)
    baseline, _, _ = module._load_pre_human_history(workspace)
    *_, current = module._construct_current_dataset(workspace)
    changed = module._changed_review_target_ids(baseline, current)
    path = workspace / "fixtures/benchmark/change_log.jsonl"
    invalid_line_number = len(path.read_bytes().splitlines()) + 1
    path.write_bytes(path.read_bytes() + b"[]\n")
    before = tree_bytes(workspace)
    with pytest.raises(
        ValueError, match=rf"change_log\.jsonl 修订日志第 {invalid_line_number} 行"
    ) as caught:
        module._validate_change_log(path, baseline, current, changed)
    assert isinstance(caught.value.__cause__, ValueError)
    assert "HumanRevisionRecord" in str(caught.value.__cause__)
    assert tree_bytes(workspace) == before


def test_formal_build_uses_unique_three_round_merge_and_is_deterministic(
    tmp_path, monkeypatch
):
    module, workspace, inputs = stage_synthetic_round3(tmp_path, monkeypatch)
    module.build(workspace)
    once = tree_bytes(workspace)
    module.build(workspace)
    assert tree_bytes(workspace) == once
    queue = [
        json.loads(line)
        for line in (workspace / "fixtures/benchmark/human_review_queue.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(queue) == 24
    current = {
        r["case"]["case_id"]: r
        for r in map(
            json.loads,
            (workspace / "fixtures/benchmark/drafts.jsonl")
            .read_text(encoding="utf-8")
            .splitlines(),
        )
    }
    assert all(
        current[r.case.case_id]["case"]["human_review_status"] != "approved"
        for r in inputs
    )


@pytest.mark.parametrize(
    "damage",
    ["missing", "duplicate", "extra", "before", "after", "noncanonical", "actor"],
)
def test_log_suffix_must_exactly_match_target_diff_before_writes(
    tmp_path, monkeypatch, damage
):
    module, workspace, _ = stage_synthetic_round3(tmp_path, monkeypatch)
    path = workspace / "fixtures/benchmark/change_log.jsonl"
    prefix = path.read_bytes()[:2585]
    rows = [json.loads(line) for line in path.read_bytes()[2585:].splitlines()]
    if damage == "missing":
        rows.pop()
    elif damage == "duplicate":
        rows.append(rows[0])
    elif damage == "extra":
        rows[0]["case_id"] = "case-extra"
    elif damage == "before":
        rows[0]["before_review_target_hash"] = "0" * 64
    elif damage == "after":
        rows[0]["after_review_target_hash"] = "0" * 64
    elif damage == "actor":
        rows[0]["actor"] = "project-owner"
    content = module._canonical_jsonl_bytes(tuple(rows))
    if damage == "noncanonical":
        content = b" " + content
    path.write_bytes(prefix + content)
    before = tree_bytes(workspace)
    with pytest.raises(ValueError, match="修订日志"):
        module.build(workspace)
    assert tree_bytes(workspace) == before


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "duplicate",
        "extra",
        "stale",
        "evidence",
        "revise",
        "reject",
        "confidence",
        "prompt",
        "input",
        "hash",
        "noncanonical",
        "precision",
        "raw",
        "raw_hash",
    ],
)
def test_round3_rejects_invalid_archive_before_writes(tmp_path, monkeypatch, damage):
    module, workspace, _ = stage_synthetic_round3(tmp_path, monkeypatch)
    path = workspace / "fixtures/benchmark/review_history/round-3-reviews.jsonl"
    rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    if damage == "missing":
        rows.pop()
    elif damage == "duplicate":
        rows.append(rows[0])
    elif damage == "extra":
        rows[0]["case_id"] = "case-extra"
    elif damage == "stale":
        rows[0]["review_target_hash"] = "0" * 64
    elif damage == "evidence":
        rows[0]["evidence_refs"] = ["unknown-chunk"]
    elif damage in ("revise", "reject"):
        rows[0].update(decision=damage, issues=["存在问题"], suggested_changes=["修订证据"])
    elif damage == "confidence":
        rows[0]["reviewer_confidence"] = 0.79
    elif damage == "prompt":
        rows[0]["prompt_hash"] = "0" * 64
    elif damage == "precision":
        rows[0]["reviewed_at"] = "2026-10-03T15:30:00.1234567+08:00"
    elif damage in {"raw", "raw_hash"}:
        raw_path = path.with_name("round-3-reviews.raw.jsonl")
        raw_rows = [json.loads(line) for line in raw_path.read_bytes().splitlines()]
        raw_rows[0]["model_name"] = "tampered-raw"
        raw_path.write_bytes(module._canonical_jsonl_bytes(tuple(raw_rows)))
        if damage == "raw":
            monkeypatch.setattr(
                module,
                "ROUND3_RAW_REVIEWS_HASH",
                hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            )
    elif damage == "noncanonical":
        pass
    elif damage == "input":
        input_path = path.with_name("round-3-inputs.jsonl")
        input_path.write_bytes(
            b"\n".join(input_path.read_bytes().splitlines()[:-1]) + b"\n"
        )
        monkeypatch.setattr(
            module,
            "ROUND3_INPUTS_HASH",
            hashlib.sha256(input_path.read_bytes()).hexdigest(),
        )
    else:
        rows[0]["model_name"] = "tampered"
    path.write_bytes(module._canonical_jsonl_bytes(tuple(rows)))
    if damage == "noncanonical":
        path.write_bytes(b" " + path.read_bytes())
    if damage != "hash":
        monkeypatch.setattr(
            module, "ROUND3_REVIEWS_HASH", hashlib.sha256(path.read_bytes()).hexdigest()
        )
    if damage not in {"raw", "raw_hash", "precision", "noncanonical", "hash"}:
        raw_path = path.with_name("round-3-reviews.raw.jsonl")
        raw_path.write_bytes(path.read_bytes())
        monkeypatch.setattr(
            module,
            "ROUND3_RAW_REVIEWS_HASH",
            hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        )
    messages = {
        "missing": "结果必须精确覆盖",
        "duplicate": "结果必须精确覆盖",
        "extra": "结果必须精确覆盖",
        "stale": "未绑定当前目标",
        "evidence": "证据引用超出环境",
        "revise": "未通过或低置信度",
        "reject": "未通过或低置信度",
        "confidence": "未通过或低置信度",
        "prompt": "提示词身份",
        "input": "输入必须精确等于",
        "hash": "固定归档哈希",
        "raw_hash": "固定归档哈希",
        "raw": "非格式差异",
        "precision": "模型规范",
        "noncanonical": "模型规范",
    }
    before = tree_bytes(workspace)
    with pytest.raises(ValueError, match=messages[damage]):
        module.build(workspace)
    assert tree_bytes(workspace) == before


def test_controlled_raw_matches_real_source_commit_and_fetch_time_is_separate():
    module = load_builder()
    source = next(
        s for s in module.SOURCES if s.source_id == "controlled-benchmark-distractors"
    )
    committed = subprocess.check_output(
        ["git", "show", f"{source.commit_sha}:{source.relative_path}"], cwd=ROOT
    )
    assert (ROOT / source.local_path).read_bytes() == module.normalize_text(
        committed.decode("utf-8")
    ).encode("utf-8")
    assert (
        hashlib.sha256((ROOT / source.local_path).read_bytes()).hexdigest()
        == source.expected_hash
    )
    assert source.fetched_at > module.FETCHED_AT
    assert module.FETCHED_AT.isoformat() == "2026-09-24T00:00:00+08:00"
