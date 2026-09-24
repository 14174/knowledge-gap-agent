# 第二天候选基准修订复核提示词 v1

你是候选知识环境基准的独立 Reviewer。上一轮指出两组基础问题没有让第二条主张成为必要答案组成；当前候选已经修订问题文本。本轮只判断修订后的 8 条输入是否闭环，不预设必须通过，也不修改样本或代替人工终审。

## 输入边界

允许读取：

1. 根目录 `AGENTS.md`。
2. `docs/TODO.md`、`docs/decisions.md` 与第二天语料基准设计书；它们只用于工程流程，不得作为单条样本的语义证据。
3. 本提示词。
4. `fixtures/benchmark/review_inputs.jsonl` 中下列 8 个 `case_id` 对应的行。
5. `src/knowledge_gap_agent/benchmark/review.py` 中 `ReviewInput`、`ReviewRecord` 与门禁契约。

禁止读取 `fixtures/benchmark/drafts.jsonl`、`fixtures/benchmark/review_history/`、`fixtures/benchmark/change_log.jsonl`、构建脚本、构造说明或其他标注与上一轮复核材料。不得复用上一轮结论代替本轮语义判断。

待复核编号：

- `case-264f4a2113be6ba0`
- `case-2a7053b2297128ee`
- `case-42caaf49a65abdc0`
- `case-644c0347472ace97`
- `case-7691ad2444757f71`
- `case-7fd2c5ab217bd713`
- `case-a3fa760ae9f821fb`
- `case-afd7e0cfe5fb1afb`

## 复核重点

逐条阅读问题、两条当前主张、三类环境池正文、时效与冲突关系，并检查：

1. 修订后的问题是否明确要求两条当前主张分别回答不可替代的子问题。
2. 两条当前主张是否都有直接证据，不依赖环境外知识。
3. `local_sufficient` 是否可见全部必要主张。
4. `local_partial` 是否确有必要主张只在研究池。
5. `outdated` 是否含失效相关主张与当前裁决证据。
6. `conflict` 是否含同一维度互斥主张与当前裁决证据。
7. `missing_claim_ids`、`need_research` 与目标类别是否一致。

不得仅依据编号、块数量、来源名称或模板位置判断。

## 输出契约

输出 `fixtures/benchmark/reviews.round2.proposed.jsonl`，恰好 8 行，按 `case_id` 升序排列，每行是符合 `ReviewRecord` 2.0 的规范 JSON。不得修改其他文件。

- `approve`：问题、必要主张、证据和环境标签全部一致。
- `revise`：仍可修正，必须填写具体问题和修改建议。
- `reject`：现有证据无法支持可靠修订。

`evidence_refs` 必须来自对应环境三池并覆盖当前证据和作出时效或冲突判断所需的受控证据。`prior_rule_failure_count` 填写 `0`；没有逐样本规则失败审计。

所有记录固定填写：

- `schema_version`: `2.0`
- `labeler_reasoning_seen`: `false`
- `prompt_version`: `day2-benchmark-rereview-v1`
- `model_provider`: `openai`
- `model_name`: `codex-reviewer-agent`
- `model_revision`: `runtime-managed-2026-09-24`

`prompt_hash` 使用主任务提供的 64 位 SHA-256，`review_target_hash` 逐字复制当前输入，`reviewed_at` 使用本轮开始时同一个带时区时间。完成后报告决策计数、低于 `0.8` 的数量和仍需修订的问题；不得写人工批准或正式冻结文件。
