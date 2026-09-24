# 实验记录

## 2026-09-24：候选基准首轮独立复核

### 目的

检查 48 条候选样本的标签、搜索决策、必需主张与环境证据是否一致。本轮只评估候选数据质量，不测量 Runtime 或模型任务性能。

### 输入与配置

- 输入：`fixtures/benchmark/review_history/round-1-inputs.jsonl`，48 条，自校验 SHA-256 为 `b5949208d2b4e0e976015c720d9e04de985e6678431f75bf760faa600b6517a8`。
- Reviewer 输出：`round-1-reviews.jsonl`，SHA-256 为 `7a112d7125d006f3050bbda1c0e941871c62a99999cb0e1c88fc28b5c1890147`。
- 提示词版本：`day2-benchmark-review-v1`；实际读取 `fixtures/benchmark/reviewer_prompt_v1.md` 原始字节所得 SHA-256 为 `5f1f17ef7e6ee0c5f9ca7ebabcb560faca51b23763501e94b27a4fd9c53399b7`，与首轮 reviews 及修订日志记录一致。
- 隔离边界：Reviewer 未读取 `annotation_reason`、复核状态、人工状态或 Labeler 长推理。

### 结果

Reviewer 原样输出为 42 条 `approve`、6 条 `revise`。6 条 `revise` 均属于 base-02、base-08 的 `local_partial`、`outdated`、`conflict`。质量审计确认两组问题对第二条必需主张的必要性表达不足，同一缺陷也影响各自的 `local_sufficient`，因此实际修订范围扩为 8 条。

修订只收紧问题文本：base-02 明确询问自定义不可变 `list` 子类的不足、选择 `tuple` 的理由和 JSON 数组兼容，不把普通 `list` 设为独立子问；base-08 明确询问完整 RAG 及异构文档转 Markdown 的理由与后续流程。来源、claims、证据、case ID 和 environment ID 不变。修订后恰 8 条 `review_target_hash` 改变，另外 40 条仍匹配首轮复核目标。

### 状态与后续

两条审计记录均标记 `human_approved=false`。当前 `reviews.jsonl` 为空，未生成正式冻结文件；下一步是对修订后的 48 条输入执行第二轮独立复审，再按既有规则进入人工终审或抽检。
