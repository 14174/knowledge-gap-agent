# 阶段一练习

共 8 题，建议用时 60–90 分钟。所有题目都能从 [GUIDE.md](GUIDE.md) 和真实代码推导。先提交自己的答案，再按 [learning/README.md](../README.md) 的三轮提示词使用 AI；不要在第一次卡住时直接打开 [SOLUTIONS.md](SOLUTIONS.md)。

## 题1：简答题（基础）

给定两个 JSON 兼容映射：

```python
left = {"b": 2, "a": 1}
right = {"a": 1, "b": 2}
```

说明 `canonical_json` 和 `sha256_hex` 对两者应产生什么关系。再回答：为什么不能据此认为数组 `[{"id": "x"}, {"id": "y"}]` 的元素顺序也会自动忽略？若输入含 `NaN`，系统应生成摘要还是早拒绝？

## 题2：简答题（应用）

一份 Markdown 文档中，同一段正文从第 10 行移动到第 14 行，标题路径和正文内容不变。根据 `chunk_id` 的组成，分别判断 `content_hash` 与 `chunk_id` 是否变化，并解释行级身份为何对证据追溯有用。补充说明：当单个段落超过 `max_chars` 时，当前实现如何处理？

## 题3：简答题（应用）

说明 12×4 环境视图如何从一份语料派生 48 条候选。比较 runtime envelope 与决策模型输入的字段边界，并指出以下字段为何不能进入模型输入：`case_id`、`category`、`missing_claim_ids`、`evidence_chunk_ids`。最后解释模型对 48 条全部给出 `approve` 后，为什么 24 条高风险候选仍不能正式冻结。

## 题4：伪代码题（应用）

编写 `build_safe_model_input` 的伪代码。

输入：一个 `BenchmarkCase`、一个 `KnowledgeEnvironment`、完整 `CorpusChunk` 集合。

输出：只含 `question` 与按环境可见顺序排列的 `visible_knowledge` 正文列表。

约束：必须重新验证输入；case 与 environment 必须匹配；块编号必须唯一；所有可见块都必须存在；输出不得含任何运行关联编号或标签字段。

边界案例：`visible_chunk_ids` 引用了不存在的块时，在产生模型载荷前早拒绝；不能用空字符串代替缺失正文。

## 题5：伪代码题（挑战）

编写“应用独立复核并决定人工升级”的伪代码。

输入：当前可信的 case、environment、chunks、claims，以及一个 `ReviewRecord`。

输出：更新后的 `review_status` 与 `human_review_status`，或明确错误。

约束：从可信输入重建 Reviewer 可见目标并复算 `review_target_hash`；校验 `case_id`、草稿状态与证据引用；模型门禁只能产生人工 `pending` 或 `not_required`；`outdated`、`conflict`、`revise`、`reject`、置信度低于 `0.8`、曾有规则失败中的任一条件都要升级人工处理；两轮记录按目标版本合并，不得改写首轮历史。

边界案例：case 的问题文本已修改，但 ReviewRecord 仍携带旧哈希时，必须在改变任何状态前拒绝。

## 题6：Trace 分析题（应用）

给定同一 `run_id`、`task_id` 和 `config_hash` 下的四条 `TraceEvent` 投影：

```text
{step: 0, event_type: run_started,    action: null,
 status: success, error_type: null}
{step: 1, event_type: action_selected, action: search,
 arguments: {query: "BM25"}, status: success, error_type: null}
{step: 2, event_type: tool_completed, action: search,
 observation_ref: null, status: failed, error_type: SearchTimeout}
{step: 3, event_type: run_finished,   action: null,
 status: success, error_type: null}
```

指出首个失败发生在哪一步，哪些字段支持该诊断。再解释：每条事件各自通过 `TraceEvent` 校验，是否足以证明这条事件序列已经从搜索超时中恢复？区分单条事件契约与跨事件语义。当前尚未实现 Runtime 和 TraceStore，不得仅凭最后一条 `run_finished success` 推断恢复成功。最后说明：如果第 2 步省略 `error_type`，会在什么阶段被拒绝。

## 题7：实验设计题（挑战）

使用 Demo 的 `CHUNKS`、`REQUIRED_CLAIM_IDS` 和 BM25 索引，固定查询为 `BM25 如何解释检索分数 人工终审 二元字组`。设计只改变 `top_k` 的配对实验，复现以下观察：`top_k=2` 返回 `chunk-token`、`chunk-formula`，`claim-human-review` 仍缺失；`top_k=3` 新增 `chunk-human-review`，该主张转为命中。写出自变量、控制变量、观测字段和停止条件，核对两个共有块的 `term_scores` 不变，并说明如果同时修改 `k1`，为什么对照失效。

## 题8：代码修改题（挑战）

在练习分支中小范围修改 [demo/02_bm25_retrieval.py](../../demo/02_bm25_retrieval.py)：让 `build_payload` 接受参数 `top_k: int = 2`，并把它传给 `BM25Index.search`。默认调用的输出契约必须保持不变；不要增加命令行框架，也不要改变查询、语料、`k1` 或 `b`。

测试或断言：在 [tests/demo/test_bm25_retrieval_demo.py](../../tests/demo/test_bm25_retrieval_demo.py) 新增测试，断言 `build_payload(top_k=1)["top_k"]` 恰有 1 条、默认 `build_payload()["top_k"]` 恰有 2 条，并核对两个载荷各自的 `result_hash == sha256_hex({k: v for k, v in payload.items() if k != "result_hash"})`。随后运行该测试文件。
