# 设计决策

## 2026-09-24：AI Coding 规范采用两层结构

### 背景

协作者需要一份可解释的完整工程规范，Codex 进入仓库时又需要短而明确的自动指令。把两者写在同一文件中，会让自动上下文过长，也会让详细规则难以维护。

### 决策

根目录 `AGENTS.md` 保存强制执行的最小规则，`docs/AI_CODING_GUIDE.md` 保存模块边界、数据契约、测试策略、审查流程和交接模板。`AGENTS.md` 链接详细规范；两者术语保持一致。

### 影响

- 新的 Codex 会话能自动获得开工顺序和工程红线。
- 协作者可以从详细规范理解规则理由和完整操作步骤。
- 修改强制规则时必须同时检查详细规范，避免两层内容冲突。

## 2026-09-24：冻结模型内部使用元组

### 背景

Pydantic 的 `frozen=True` 只阻止字段重新赋值，不能阻止 `list.append()` 等原地修改。自定义不可变 `list` 子类仍可通过未绑定的基类方法绕过，并会破坏深复制和 Pickle 协议。

### 决策

冻结模型的集合字段在 Python 内部使用 `tuple`。Pydantic JSON 模式和 JSONL 持久化继续输出数组。调用方需要修改集合时，必须显式构造新模型。

### 影响

- 模型创建后不能因容器原地修改而绕过字段校验。
- 内容哈希、审计记录和冻结数据保持一致。
- Python 属性类型由可变列表改为不可变元组；磁盘格式不变。
- 测试必须覆盖深复制、Pydantic 深复制、Pickle 往返和 JSON 数组输出。

## 2026-09-24：Reviewer 结果绑定完整草稿目标

### 背景

仅用 `case_id` 和证据引用关联复核结果时，问题、答案键、类别、草稿状态或环境池变化后，旧复核仍可能被错误应用或冻结。编号相同不能证明 Reviewer 检查的是当前内容。

### 决策

`ReviewRecord` 升级为 `schema_version=2.0`，新增必填的 `review_target_hash`。哈希对象必须与 Reviewer 实际可见输入完全相同：先由 case、environment、corpus chunks 与 claims 构造不含哈希的 `ReviewTargetInput`，再对其规范 JSON 求哈希，最后生成 `ReviewInput`。case 白名单明确排除 Reviewer 看不到的 `annotation_reason`，以及作为复核输出的 `review_status`、`human_review_status`；环境三池则展开为 Reviewer 可见的块编号、来源、标题路径、正文与主张关联，相关主张包含陈述、时效、冲突边和证据映射。`apply_review_gate`、候选冻结和正式冻结均从可信语料重新构造同一输入，不信任复核文件自带哈希。

`ReviewInput` 还在模型级 `after` 校验中移除 `review_target_hash`、还原同一个 `ReviewTargetInput` 并复算哈希。因此 Python 构造、`model_validate` 和 `model_validate_json` 都拒绝被改写的磁盘输入。`model_copy` 本身不执行验证；跨信任边界时必须按公共入口模式先 `model_dump(mode="python")` 再重新验证。

### 影响

- 问题、答案键、类别、`draft_status`、环境池、Reviewer 可见块内容或相关主张语义变化都会使旧复核早拒绝；只改变 `annotation_reason`、`review_status`、`human_review_status` 不改变复核目标哈希。
- case、environment、chunk 与 claim 的纳入或排除字段均由显式常量约束；模型字段漂移会在生产入口早拒绝，必须先决定 Reviewer 可见性。
- `evidence_refs` 可引用对应环境三池并集中的任一块，不能引用环境外块。
- 内容变化后必须重新生成 Reviewer 输入并重新复核，不能沿用旧结论。
- `reviews.jsonl` 非空时，确定性重建会先校验所有目标哈希；失配时不覆盖原文件。
- 该机制只防止陈旧复核，不产生复核结论，也不替代人工批准。

## 2026-09-24：Reviewer 修订保留不可变首轮历史

### 背景

首轮独立 Reviewer 对 48 条候选给出 42 条 `approve`、6 条 `revise`。质量审计发现 base-02 与 base-08 的两条 `local_sufficient` 也具有相同的问题必要性缺陷，因此实际修订范围是两个基础问题的全部 8 条候选。若覆盖首轮输入或原 Reviewer 输出，会丢失结论形成时的精确上下文；若把质量审计补充项改写进 Reviewer 输出，则会伪造 Reviewer 结论。

### 决策

首轮 `review_inputs.jsonl` 和 Reviewer 原输出按原始字节归档到 `fixtures/benchmark/review_history/`，并固定文件 SHA-256、提示词版本与提示词哈希。修订只收紧 base-02、base-08 的问题文本，不改来源、claims、证据或不透明编号。`change_log.jsonl` 每个基础问题一条记录，分别列出原 Reviewer 的 3 条 `revise` 与质量审计补充的 1 条 `local_sufficient`，`actor` 明确为独立 Reviewer 与质量审计，`human_approved=false`。

### 影响

- 修订后恰 8 条 `review_target_hash` 变化，其余 40 条仍与首轮输入匹配。
- 首轮 6 条 `revise` 原样保留，不能扩写成 8 条 Reviewer 结论。
- 当前 `reviews.jsonl` 继续为空，48 条修订后输入需重新独立复审。
- 本次修订和审计记录不代表人工批准，也不允许生成正式冻结文件。
- base-02 只询问现有 `current-02-a`、`current-02-b` 能直接回答的三项：自定义不可变 `list` 子类为何不足、为何选择 `tuple`、如何保持 JSON 数组兼容；普通 `list` 不单列为问题要求。
- `change_log.jsonl` 是版本化非空夹具，初始化只允许通过受审提交或人工流程完成。构建器对它没有写权限：缺失或零字节时早拒绝；非空时在其他产物写盘前只读校验两条确定性 Reviewer 修订前缀与后续规范 JSON 对象，并逐字节保留人工流程拥有的追加记录。
- 首轮提示词哈希不能只信任常量或复核记录自报。构建器必须读取 `reviewer_prompt_v1.md` 原始字节求 SHA-256，再与固定预期、首轮 reviews 和修订前缀的 `prompt_hash` 交叉核对；任一不一致均在写盘前拒绝。
