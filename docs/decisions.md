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

## 2026-09-24：多轮复核按目标版本合并并通过公共门禁

### 背景

首轮 48 条复核中有 8 条候选因问题文本修订而产生新目标哈希；其余 40 条内容与哈希未变化。若统一重写复核元数据，会丢失真实轮次、提示词和时间；若构建器直接改写状态字段，则会绕过 `apply_review_gate` 的目标哈希、证据引用与人工升级规则。

### 决策

首轮未变化 40 条沿用首轮原 ReviewRecord，修订 8 条严格使用第二轮原 ReviewRecord，按 `case_id` 形成唯一的规范 JSONL 合并。当前 `reviews.jsonl` 不是“任意合法且哈希匹配的 48 条记录”：非空时必须逐字节等于该归档合并，提示词、模型、时间、结论、置信度、证据引用、顺序或格式任一变化都拒绝。两轮提示词哈希均从实际文件字节计算并与归档记录核对；通过这一检查后，构建器才逐条调用可信 `apply_review_gate` 并写草稿。空 reviews 仍产生 pending 候选和空人工队列。

人工队列采用最小白名单，只记录 `case_id`、高风险类别、复核目标哈希、`high_risk_category` 触发原因、真实模型决策、置信度和提示词版本。它不包含人工批准字段，也不替代 `change_log.jsonl` 的人工审计职责。

### 影响

- 第二轮 8 条原始输入与 Reviewer 输出单独归档，首轮历史不改写。
- 当前 48 条模型复核均为 `approve`，但 24 条 `outdated`、`conflict` 仍为人工 `pending`。
- 模型复核完成不等于正式冻结；人工状态未完成前不得生成正式发布数据或结果数字。
- 当前 reviews 的每条模型、提示词版本、哈希和时间均保持其真实来源，不做跨轮统一填充。

## 2026-09-25：正式冻结只接受绑定当前目标的人工记录

### 背景

正式冻结原先只检查 `BenchmarkCase.human_review_status`。Pydantic 的 `model_copy()` 不重新校验字段，调用方可以把高风险 case 的缓存状态改成 `approved`，却不提供人工审核者、理由、时间和审核目标。状态值不能证明真实人工审核发生过。

破坏性夹具测试还曾直接改写版本化 `fixtures/`，再在 `finally` 中恢复。并行读取者仍会看到临时的损坏内容，恢复文件不能消除这段污染窗口。

### 决策

- 正式冻结只把 `HumanReviewRecord` 作为人工结论来源。每条记录包含审核者、理由、带时区的时间和当前 `review_target_hash`。
- 正式冻结用可信 case、environment、chunks 和 claims 重算模型门禁与人工需求。`human_review_status` 只是派生缓存，不能授权冻结。
- 人工记录的 case 集合必须与当前必审集合精确相等。缺失、重复、额外、陈旧以及 `revise/rejected` 结论均在写盘前拒绝。
- 候选冻结不消费人工结论，并拒绝非空人工记录。它只派生 `pending/not_required`。
- `HumanRevisionRecord` 只记录人工 `revise` 被实际应用后的内容变化。它不表示批准，也不能替代新目标上的模型复核与人工终审。
- 任何通过 `model_copy()`、`model_construct()` 或外部反序列化进入公共边界的模型，都先执行 `model_dump(mode="python")`，再用对应 Pydantic 模型重新验证。
- 夹具构建脚本使用显式 `--workspace-root`。破坏性测试只能在 `tmp_path` 的夹具副本运行，并在每条测试后核对版本化夹具哈希。

### 影响

- 手填 `human_review_status=approved` 不再能绕过正式冻结。
- 内容变化会改变 `review_target_hash`，旧人工记录自动失效。
- 人工记录只进入审计集，不进入 runtime 或 labels。
- 当前 24 条高风险候选仍为 `pending`。仓库不创建 `human_reviews.jsonl`、正式冻结文件或阶段标签，直到真实人工审核完成。
