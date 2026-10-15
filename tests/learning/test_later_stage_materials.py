"""后续课程沿用阶段一的题目、答案和链接契约。"""
from collections import Counter
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).parents[2]
STAGES = sorted((ROOT / "learning").glob("stage-0[2-5]-*"))


@pytest.mark.parametrize("stage", STAGES, ids=lambda path: path.name)
def test_later_stage_exercise_contract(stage):
    text = (stage / "EXERCISES.md").read_text(encoding="utf-8")
    matches = list(re.finditer(
        r"(?m)^## 题([1-8])：(简答题|伪代码题|Trace 分析题|实验设计题|代码修改题)（(基础|应用|挑战)）$", text))
    assert [m[1] for m in matches] == list("12345678")
    assert Counter(m[2] for m in matches) == {
        "简答题": 3, "伪代码题": 2, "Trace 分析题": 1, "实验设计题": 1, "代码修改题": 1}
    for index, match in enumerate(matches):
        block = text[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(text)]
        if match[2] == "伪代码题":
            assert all(label in block for label in ("输入：", "输出：", "约束：", "边界案例："))
        if match[2] == "代码修改题":
            assert "测试或断言：" in block


@pytest.mark.parametrize("stage", STAGES, ids=lambda path: path.name)
def test_later_stage_solution_contract(stage):
    text = (stage / "SOLUTIONS.md").read_text(encoding="utf-8")
    matches = list(re.finditer(r"(?m)^## 题([1-8])$", text))
    assert [m[1] for m in matches] == list("12345678")
    for index, match in enumerate(matches):
        block = text[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(text)]
        assert all("### " + label in block for label in ("提示", "参考答案", "评分点", "常见错误"))


@pytest.mark.parametrize("stage", STAGES, ids=lambda path: path.name)
def test_later_stage_material_links(stage):
    for name in ("GUIDE.md", "LAB.md", "EXERCISES.md", "SOLUTIONS.md"):
        path = stage / name
        text = path.read_text(encoding="utf-8")
        for link in re.findall(r"\]\(([^)]+)\)", text):
            if "://" in link or link.startswith("#"):
                continue
            assert (path.parent / link.split("#", 1)[0]).exists(), (path, link)
