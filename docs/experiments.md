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

两条审计记录均标记 `human_approved=false`。首轮修订完成时 `reviews.jsonl` 为空，尚未生成正式冻结文件；随后进入第二轮独立复审。

## 2026-09-24：修订候选第二轮复核与模型门禁

### 目的与输入

第二轮仅复核 base-02、base-08 修订后的 8 条当前输入。归档输入 SHA-256 为 `4351eebc1cdb6c2391c3c63c5c1e0ae981e1895f6f9f10d9fa17090b716caea3`，Reviewer 原输出 SHA-256 为 `94ae44ab604261c580d0705ac7615183810dfd38b782eca1b9aaa6b8759bf85d`。提示词版本为 `day2-benchmark-rereview-v1`，提示词原始字节 SHA-256 为 `6bd78ec097255e1334ff6829912025ace6060906b04bcaef775103d354baf95f`。

### 结果

第二轮 8 条全部为模型 `approve`，无 `revise` 或 `reject`，置信度均不低于 `0.8`。与首轮未变化的 40 条合并后，当前 48 条 reviews 全部为模型 `approve`，最低置信度为 `0.95`。构建器使用可信 `apply_review_gate` 逐条执行门禁，结果为：

当前 48 条复核的合并规则是归档唯一映射，不接受任意合法替代记录：8 条修订 case 原样取第二轮记录，其余 40 条原样取首轮记录，按 `case_id` 排序为规范 JSONL。构建时先核对两轮提示词实际文件哈希和归档，再对 `reviews.jsonl` 做整文件字节比对，最后才执行模型门禁。

- 48 条 `review_status=approved`；
- 24 条 `local_sufficient`、`local_partial` 为 `human_review_status=not_required`；
- 12 条 `outdated` 与 12 条 `conflict` 为 `human_review_status=pending`，全部进入人工复核队列。

### 状态与限制

上述数字仅描述固定候选集的复核流程，不是 Runtime 性能、成本收益或简历结果数字。当前 24 条高风险候选仍未获得人工批准，`change_log.jsonl` 未追加人工结论，也未生成正式 `runtime`、`labels`、`audit` 或冻结基准。

## 2026-09-25：阶段一自动验收与人工门禁交接

### 自动验收记录

阶段一可信人工门禁修复完成代码与清单实现后，按以下命令分层验证：

```powershell
uv run python -m pytest tests/benchmark/test_human_review_models.py tests/corpus/test_models.py -q
uv run python -m pytest tests/benchmark/test_validation.py tests/benchmark/test_freeze.py -q
uv run python -m pytest tests/benchmark/test_fixture_dataset.py -q
uv run python -m pytest tests/learning -q
uv run python demo/01_config_trace.py
uv run python demo/02_bm25_retrieval.py
uv lock --check
git diff --check
git diff -- fixtures
uv run python -m pytest -q
```

2026-09-25 最终分层验收后的全量测试结果为 `614 passed, 1 skipped`，耗时 `134.33s`。跳过项是 Windows 符号链接权限相关的条件跳过。测试代码不固定这个动态总数；后续测试集合变化时，以最新一次真实命令输出更新本段。

两项 Demo 已实际运行并正常退出。`uv lock --check`、`git diff --check` 通过，`git diff -- fixtures` 无输出。破坏性夹具测试均在显式 `--workspace-root` 的临时副本运行。

### 人工门禁状态

已交付[阶段一人工终审清单](阶段一人工终审清单.md)。24 条高风险候选仍为人工 `pending`，其中 `outdated` 与 `conflict` 各 12 条。清单含 47 个去重证据块，所有人工结论字段为空。

模型复核的 48 条 `approve` 不能替代真实人工批准。当前仓库没有 `human_reviews.jsonl`、正式冻结文件或 `learn-v0.1-eval-contract` 标签。必须先完成 24 条真实人工审核，再由正式冻结器校验 `HumanReviewRecord` 的精确集合、当前目标哈希和结论。
