# 当前待办

## 10 天首轮实验冲刺

- [ ] 第 1–2 天：完成实验合同、冻结语料与人工标注。
  - [x] 第 1 天：完成配置/Trace Demo、实验合同与首日学习材料。
  - [ ] 第 2 天：按[语料与基准数据设计](superpowers/specs/2026-09-24-第二天语料与基准数据设计.md)完成固定语料、48 条基准、独立复核、BM25 Demo 与学习材料。
    - [x] 固定 8 份来源并由确定性脚本构造 12×4 共 48 条候选草稿。
    - [x] 分离评测器关联信封与决策模型输入，模型只接收问题和可见知识正文。
    - [ ] 由独立 Reviewer Agent 全量复核候选草稿，并执行人工升级门禁。
- [ ] 第 3–4 天：完成最小 Runtime、Trace/Replay 与 E0 基线。
- [ ] 第 5–6 天：完成长期知识检索、充分性 Gate 与 E1/E2。
- [ ] 第 7–8 天：完成证据写回、知识复用实验与 E3。
- [ ] 第 9–10 天：完成 Candidate Skill Gate、统计报告和简历证据卡。

## 渐进式学习课程

- [ ] 建立 `learning/` 总入口和五阶段目录。
- [ ] 每阶段补齐 `GUIDE.md`、`LAB.md`、`EXERCISES.md` 与 `SOLUTIONS.md`。
- [ ] 每阶段提供 8 道练习，其中至少 2 道为伪代码题。
- [ ] 增加 AI 辅导提示词与按评分点反馈的使用说明。
- [ ] 增加课程文档校验与阶段 Demo 校验。
- [ ] 阶段验收通过后依次创建 `learn-v0.1-eval-contract`、`learn-v0.2-react-runtime`、`learn-v0.3-knowledge-gap`、`learn-v0.4-knowledge-evolution` 和 `learn-v0.5-skill-gate` 标签。

详细范围、Demo、指标与验收条件见 [冲刺版开发计划](冲刺版开发计划.md)。
课程结构、练习契约和 AI 辅导流程见 [渐进式学习课程设计](superpowers/specs/2026-09-21-渐进式学习课程设计.md)。

## 工程协作

- [x] 建立仓库级 `AGENTS.md` 和 [AI Coding 工程规范](AI_CODING_GUIDE.md)，固定 Codex 接手、实现、审查、验证与交接流程。
