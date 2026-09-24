# 阶段一参考答案

参考答案给出一种满足约束的解法，不要求逐字一致。评分依据是推理、边界和可核验步骤，不按关键词机械评分。

## 题1

### 提示

分别检查映射键、数组位置和非有限浮点数由哪一层处理。

### 参考答案

两个映射经 `sort_keys=True` 和紧凑序列化后都得到 `{"a":1,"b":2}`，所以 `canonical_json(left) == canonical_json(right)`，两个 SHA-256 摘要也相同。

数组仍保留输入次序。`canonical_json` 只排序对象键，不会把数组当集合重排，因此 `[x, y]` 与 `[y, x]` 通常产生不同文本和摘要。如果某字段在业务上是无序集合，调用方必须在进入 `canonical_json` 前明确排序；环境哈希就是这样处理三组块编号的。

`NaN` 不是合规 JSON 数值。当前实现设置 `allow_nan=False`，应抛出错误并停止，不能为非法输入生成摘要。

### 评分点

- 指出两个映射的规范 JSON 和摘要相同。
- 区分“对象键排序”与“数组顺序保留”。
- 说明集合语义由业务层先排序，而不是哈希函数猜测。
- 指出 `NaN` 必须早拒绝。

### 常见错误

把稳定哈希解释成“任意排列都相同”，会把有序列表的语义抹掉。另一种错误是先让 JSON 库输出 `NaN` 再计算摘要，这会固定一个不符合当前契约的非法表示。

## 题2

### 提示

把正文内容身份和证据位置身份分开判断。

### 参考答案

正文和规范化方式未变，所以 `content_hash` 不变。`chunk_id` 的输入包含 `source_id`、`heading_path`、`start_line`、`end_line`、`content_hash`；段落从第 10 行移动到第 14 行会改变行范围，因此 `chunk_id` 改变。

这让系统能同时回答两个问题：内容是不是同一份，以及引用的位置是不是同一处。如果只用正文哈希，相同段落在文档中重复出现时无法区分证据位置。

`max_chars` 是段落组合阈值，不是字符硬切阈值。单段超过限制时仍保留整个段落作为一个块，所以该块可以大于 `max_chars`。

### 评分点

- 正确判断 `content_hash` 不变。
- 正确判断包含行范围的 `chunk_id` 变化。
- 解释行号对重复正文和证据定位的作用。
- 说明超长单段不硬切。

### 常见错误

认为 `chunk_id` 只由正文决定，会漏掉标题路径和行范围。把 `max_chars` 当成绝对块长并在段落中间截断，也不符合当前实现。

## 题3

### 提示

先画出“单一证据池 → 环境三池 → runtime envelope → 模型白名单”的数据流，再判断谁需要编号、谁不能看标签。

### 参考答案

固定语料只存一份。12 个基础问题分别派生 `local_sufficient`、`local_partial`、`outdated`、`conflict` 四个环境，每个环境用互斥的可见、研究、排除块编号表示，因此共有 48 条候选。

runtime envelope 供评测器关联数据，可以含 `case_id`、`base_question_id`、`question`、`environment_id`、`visible_chunk_ids`。决策模型输入必须重新投影，只含 `question` 和 `visible_knowledge` 正文。

`category`、`missing_claim_ids`、`evidence_chunk_ids` 直接或间接给出目标判断和证据位置，属于标签泄漏。`case_id` 虽不直接给答案，但它是可枚举的关联编号，可能被用来查表或记忆样本，也没有完成决策所需的语义价值，因此不进入模型输入。

模型复核与人工终审是不同阶段。当前 48 条模型记录均为 `approve`，但 12 条 `outdated` 和 12 条 `conflict` 由规则强制进入人工队列，状态仍为 `pending`。正式冻结要求这些高风险样本取得真实人工结论，不能把模型一致意见当作人工批准。

### 评分点

- 说明 12 个基础问题各有 4 个受控环境，而不是同义改写。
- 区分 runtime envelope 和模型输入的用途与字段。
- 对四个禁止字段给出泄漏或关联风险解释。
- 指出 24 条高风险候选的人工门禁仍未完成。

### 常见错误

直接把 runtime envelope 发送给模型，会绕过白名单。把 48 个 `approve` 写成“人工已经确认”则混淆了模型复核和人工终审。

## 题4

### 提示

先在信任边界重新验证对象，再建立唯一块索引，最后才投影正文。

### 参考答案

一种满足约束的伪代码：

```text
function build_safe_model_input(raw_case, raw_environment, raw_chunks):
    case = BenchmarkCase.validate(raw_case.to_python())
    environment = KnowledgeEnvironment.validate(raw_environment.to_python())

    if case.environment_id != environment.environment_id:
        error("case 与 environment 不匹配")

    chunks_by_id = empty map
    for raw_chunk in raw_chunks:
        chunk = CorpusChunk.validate(raw_chunk.to_python())
        if chunk.chunk_id in chunks_by_id:
            error("重复 chunk_id")
        chunks_by_id[chunk.chunk_id] = chunk

    visible_knowledge = empty list
    for chunk_id in environment.visible_chunk_ids:
        if chunk_id not in chunks_by_id:
            error("可见块不存在")
        visible_knowledge.append(chunks_by_id[chunk_id].text)

    payload = {
        "question": case.question,
        "visible_knowledge": visible_knowledge,
    }
    assert keys(payload) == {"question", "visible_knowledge"}
    return payload
```

边界案例在索引查找阶段抛错，模型调用尚未发生，也不会用空正文代替未知块。

### 评分点

- 在公共入口重新验证 case、environment 和 chunk。
- 校验 case/environment 配对与 chunk 唯一性。
- 按环境给定顺序解析每个可见块，未知引用早拒绝。
- 输出严格限制为两个白名单字段。
- 明确不含研究池、排除池、关联编号与标签。

### 常见错误

用字典推导式覆盖重复 `chunk_id` 会静默选择后一个块。另一个错误是返回 `visible_chunk_ids` 而非正文，这仍然把运行关联编号交给了模型。

## 题5

### 提示

状态变化之前先重建复核目标。人工升级是规则的或关系，只要一个条件成立就进入 `pending`。

### 参考答案

一种满足约束的伪代码：

```text
function apply_independent_review(case, environment, chunks, claims, review):
    case = revalidate(case)
    environment = revalidate(environment)
    review = revalidate(review)

    if case.case_id != review.case_id:
        error("case_id 不匹配")
    if case.draft_status != "validated":
        error("草稿尚未通过规则校验")
    if case.review_status != "pending":
        error("复核状态不是初始 pending")

    target = build_review_target_from_trusted_inputs(
        case, environment, chunks, claims
    )
    expected_hash = sha256(canonical_json(target))
    if review.review_target_hash != expected_hash:
        error("陈旧或错误的 review_target_hash")

    environment_chunks = (
        target.environment.visible_chunks
        + target.environment.research_chunks
        + target.environment.excluded_chunks
    )
    environment_ids = {chunk.chunk_id for chunk in environment_chunks}
    if any(ref not in environment_ids for ref in review.evidence_refs):
        error("复核证据越界")
    if case.human_review_status in {
        HumanReviewStatus.APPROVED,
        HumanReviewStatus.REJECTED,
    }:
        error("人工终态不可由模型门禁覆盖")

    review_status = map_decision(review.decision)
    needs_human = (
        case.category in {"outdated", "conflict"}
        or review.decision in {"revise", "reject"}
        or review.reviewer_confidence < 0.8
        or review.prior_rule_failure_count > 0
    )
    human_review_status = "pending" if needs_human else "not_required"
    return copy(case, review_status, human_review_status)
```

若两轮输入中只有 8 条目标发生变化，合并时这 8 条取第二轮完整记录，其余 40 条保留首轮完整记录，再按 `case_id` 生成规范 JSONL。不能为了格式统一而重写首轮提示词、模型、时间或置信度。

问题文本已修改会改变 Reviewer 可见目标，因此旧哈希必须在任何状态更新前拒绝。即便旧记录的 `decision` 是 `approve`，也不能继续使用。

### 评分点

- 从可信 case、环境、块和主张重建目标并复算哈希。
- 按 `target.environment` 的三组 chunk 对象读取 `chunk_id`，检查证据引用。
- 在状态变化前检查 case 关联、草稿状态与人工 `approved/rejected` 终态。
- 正确实现六类人工升级条件及 `0.8` 严格阈值。
- 门禁只产生 `pending` 或 `not_required`，不制造人工结论。
- 说明两轮复核按目标版本合并并保留原始历史。
- 陈旧哈希在修改状态前早拒绝。

### 常见错误

只比较 `case_id` 会让旧复核套到新问题。直接相信 ReviewRecord 自报的哈希也不够，可信输入必须独立重算。`ReviewTargetInput` 的块位于 `target.environment` 下，若读取不存在的 `target.visible_chunk_ids`，伪代码与真实模型脱节。模型门禁若覆盖人工终态，会抹掉已有人工结论。把 `reviewer_confidence == 0.8` 判为低置信度同样不符合“低于 0.8”的规则。

## 题6

### 提示

先按 `step` 找到第一条 `status=failed` 的事件，再分别判断“单条对象是否合法”和“整条事件链是否说得通”。

### 参考答案

首个失败在 `step=2`。诊断证据是 `event_type=tool_completed`、`action=search`、`status=failed`、`error_type=SearchTimeout`，同时 `observation_ref=null` 表明没有可引用的成功工具结果。

四条记录分别看都能满足当前单条事件契约：失败事件带非空 `error_type`，成功事件不带错误类型，步骤也都是非负整数。但单条事件合法不代表跨事件语义有效。序列在搜索失败后直接出现 `run_finished success`，中间没有重试、降级、错误处理或恢复事件。当前项目又没有实现 Runtime 和 TraceStore，因此无法知道这条成功结束事件由什么状态转移产生，也不能凭末事件推断“已经恢复”。最多只能说：四个 `TraceEvent` 对象各自可构造，而整条链存在未解释的状态跳转。

如果 `step=2` 保持 `status=failed` 却省略 `error_type`，`TraceEvent.validate_status_error` 会在对象构造或反序列化校验时拒绝它。非法事件不会进入后续序列分析。

### 评分点

- 把首个失败定位到 `step=2` 的 `tool_completed`。
- 使用 `status`、`error_type`、`action` 和 `observation_ref` 支持诊断。
- 区分单条事件契约与跨事件语义，不把对象合法等同于状态机合法。
- 指出当前没有 Runtime/TraceStore，不能从 `run_finished success` 推断恢复。
- 说明失败事件缺少 `error_type` 会在构造或反序列化校验时拒绝。

### 常见错误

只看最后一条成功事件并宣布运行恢复，会越过当前实现边界。另一个错误是把 `error_type` 当作可选诊断文本；对失败事件而言，它是构造契约的一部分，缺失时不会产生合法 Trace。

## 题7

### 提示

让两组运行共享同一个索引和查询，只把搜索截断值作为函数参数。

### 参考答案

固定查询为 `BM25 如何解释检索分数 人工终审 二元字组`。在当前 Demo 语料上实测：`top_k=2` 返回 `chunk-token`、`chunk-formula`；`top_k=3` 在相同顺序后新增 `chunk-human-review`。因此 `claim-human-review` 从缺失变为命中，共有块的分项得分保持不变。

实验设计：

```text
自变量：top_k
取值：2（对照）、3（处理）
控制变量：CHUNKS、块顺序、固定查询、分词器、k1=1.5、b=0.75、
          REQUIRED_CLAIM_IDS、主张映射、代码版本
观测字段：返回 chunk_id、每块 score、term_scores、hit_claim_ids、
          missing_claim_ids
停止条件：两组各完成一次确定性运行并保存完整载荷；若共享块的
          term_scores 不同，先判为控制变量被破坏，不解释命中差异
```

实测对照为：

```text
top_k=2:
  chunk_ids = [chunk-token, chunk-formula]
  hit_claim_ids = [claim-formula]
  missing_claim_ids = [claim-human-review]

top_k=3:
  chunk_ids = [chunk-token, chunk-formula, chunk-human-review]
  hit_claim_ids = [claim-formula, claim-human-review]
  missing_claim_ids = []
```

先确认两组共享同一个索引对象和查询，再逐项比较 `chunk-token`、`chunk-formula` 的 `term_scores`；两组应完全相同。新增的第 3 条结果负责补上人工终审主张。

若同时修改 `k1`，自变量就有两个。`k1` 会改变词频饱和项，从而改变每个块的分数甚至排序；此时无法判断命中变化来自扩大返回数量，还是来自得分函数变化。

### 评分点

- 使用指定查询，准确记录两个截断值的块顺序与主张命中变化。
- 只有一个自变量，并给出至少两个取值。
- 固定查询、语料、分词、`k1`、`b` 和主张映射。
- 同时记录 `term_scores` 与主张命中/缺失字段。
- 给出控制变量破坏时的停止条件。
- 解释同时改 `k1` 会产生混杂。

### 常见错误

只记录结果数量而不记录块编号和主张命中，无法回答实验问题。把 `top_k` 与 `k1` 一起改，再把差异全部归因于 `top_k`，属于多变量混杂。

## 题8

### 提示

只把硬编码的 `2` 提升为带默认值的函数参数；结果哈希仍应最后计算。

### 参考答案

最小代码改动是：

```python
def build_payload(top_k: int = 2) -> dict[str, object]:
    index = BM25Index.build(CHUNKS)
    results = index.search(QUERY, top_k=top_k)
    # 其余逻辑保持不变
```

测试可以写成：

```python
import importlib

from knowledge_gap_agent.utils.canonical import sha256_hex


EXPECTED_DEFAULT_RESULT_HASH = "ba3825642dbdcdf2018cea9d3f111224d9bdb2dc78b91efcb55d83842634f44c"


def test_build_payload_accepts_top_k_without_changing_default_contract() -> None:
    demo = importlib.import_module("demo.02_bm25_retrieval")
    one = demo.build_payload(top_k=1)
    default = demo.build_payload()

    assert len(one["top_k"]) == 1
    assert len(default["top_k"]) == 2
    assert default["result_hash"] == EXPECTED_DEFAULT_RESULT_HASH
    for payload in (one, default):
        unhashed = {key: value for key, value in payload.items() if key != "result_hash"}
        assert payload["result_hash"] == sha256_hex(unhashed)
```

运行：

```powershell
uv run python -m pytest tests/demo/test_bm25_retrieval_demo.py -v
```

这道题只要求练习分支中的小改动；当前课程材料本身没有声称仓库已经采用该参数接口。

### 评分点

- `build_payload` 新增 `top_k: int = 2`，默认行为保持两条结果。
- 参数直接传给 `search`，没有复制检索逻辑。
- 测试同时覆盖显式 1 和默认 2。
- 默认载荷仍等于当前固定 `result_hash`，防止无关输出漂移。
- 两个载荷都从排除 `result_hash` 后的完整内容复算摘要。
- 没有顺带修改查询、语料、BM25 参数或引入命令行框架。

### 常见错误

只改测试期望而不把参数传给 `search`，显式调用仍会返回两条。另一个错误是对包含旧 `result_hash` 的载荷再次哈希，这与 Demo 的计算顺序不同。
