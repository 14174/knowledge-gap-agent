# 阶段一：评测契约、语料与候选基准

本章对应学习材料提交前的已验证实现 `3f92ae5a2e6bae78bb54759fdacc18f81d8d5960`，预计阅读 30–45 分钟。当前产物是 48 条候选数据，不是正式基准：模型复核已覆盖 48 条并全部给出 `approve`，其中 12 条 `outdated` 和 12 条 `conflict` 仍是人工 `pending`。正式冻结尚未完成，也没有可报告的实验提升数字。

## 真实失败案例

首轮独立复核并没有直接得到可用的最终候选。48 条复核结果中，42 条为 `approve`，6 条为 `revise`。随后质量审计发现，`base-02`、`base-08` 的两个 `local_sufficient` 样本与已退回样本有相同的问题必要性缺陷，实际修订范围因此从 6 条扩大到 8 条。

这里有两个容易犯的错误。第一，把质量审计补充的 2 条写成 Reviewer 的原始结论，会篡改审计历史。第二，修订问题文本后继续沿用旧 `review_target_hash`，会让复核记录错误绑定到新内容。

实际处理保留首轮输入和输出的原始字节，只修改 8 条候选问题，再对这 8 条执行第二轮独立复核。当前 `reviews.jsonl` 由首轮未变化的 40 条记录和第二轮 8 条记录唯一合并，不能把两轮元数据统一改写。最终 48 条模型复核均为 `approve`，但模型一致意见不等于人工批准；24 条高风险候选仍等待人工终审。

相关事实可在 [docs/decisions.md](../../docs/decisions.md)、[fixtures/benchmark/review_history](../../fixtures/benchmark/review_history) 和 [fixtures/benchmark/change_log.jsonl](../../fixtures/benchmark/change_log.jsonl) 中核对。

## 可以运行和观察什么

### 配置与 Trace 演示

运行：

```powershell
uv run python demo/01_config_trace.py
```

[demo/01_config_trace.py](../../demo/01_config_trace.py) 展示三件事：

1. 同一配置仅改变字段输入顺序，输出 `hash_stable=True`；
2. 合法 `TraceEvent` 的 JSON 含 `agent`、`status`、`config_hash` 和 `usage.total_tokens`；
3. 构造 `status=failed` 但缺少 `error_type` 的事件时，Pydantic 在对象创建阶段拒绝输入，演示输出 `invalid_trace_rejected=True`。

这不是 Runtime 的执行轨迹。它只证明配置身份与 Trace 数据契约已经可执行。

### BM25 检索演示

运行：

```powershell
uv run python demo/02_bm25_retrieval.py
```

[demo/02_bm25_retrieval.py](../../demo/02_bm25_retrieval.py) 只读取代码内的固定小语料，不联网，也不调用模型。输出是单行规范 JSON，可观察：

- `query_tokens`：确定性分词结果；
- `top_k`：块编号、总分与每个查询词项的 `term_scores`；
- `hit_claim_ids` 和 `missing_claim_ids`：返回块覆盖了哪些必需主张；
- `index_hash`、`environment_hash`、`result_hash`：索引、环境和结果的稳定身份。

结果中存在 `missing_claim_ids` 不代表对应主张不在语料里。演示特意让其中一个主张存在于未进入前二名的块中，用来区分“语料没有证据”和“本次检索没有返回证据”。

## 输入、输出、依赖和非职责

| 模块 | 输入 | 输出 | 直接依赖 | 非职责 |
|---|---|---|---|---|
| `utils/canonical.py` | JSON 兼容对象 | 规范 JSON、256 位摘要，以 64 个小写十六进制字符表示 | Python `json`、`hashlib` | 不决定哪些业务字段应进入哈希 |
| `corpus/chunking.py` | 已规范化的 `SourceDocument`、`max_chars` | 保留标题路径和行号的 `CorpusChunk` | 语料模型、内容哈希 | 不分词、不排序、不判断主张真伪 |
| `retrieval/tokenizer.py` | 查询或块正文 | 中文二元字组、英文数字标识符词项 | Python 正则与 Unicode 名称 | 不做语义分词或同义词扩展 |
| `retrieval/bm25.py` | 块快照、查询、`top_k` | 排序结果、总分、逐词项贡献 | 确定性分词器 | 不决定是否应该研究，不修改语料 |
| `benchmark/validation.py` | case、环境、块、主张 | 结构化校验问题，或运行/模型白名单载荷 | 基准与语料模型 | 不生成模型复核意见，不写人工结论 |
| `benchmark/review.py` | 当前可信 case、环境、语料和复核记录 | Reviewer 可见输入、目标哈希、门禁后的状态 | 规范哈希、显式字段白名单 | 不把模型结论升级成人工批准 |
| `benchmark/freeze.py` | 已校验 case、review、语料 | 运行集、标签集、审计集及整体哈希 | 校验与复核门禁 | 不绕过人工终审，不执行 Runtime |

依赖方向是“契约和语料 → 检索与校验 → 复核与冻结”。BM25 不读取标签，模型输入构造也不读取答案字段。保持这条边界，才能让后续实验判断检索或 Gate 是否有效，而不是让答案通过数据结构泄漏进去。

## 规范 JSON 与 SHA-256

[src/knowledge_gap_agent/utils/canonical.py](../../src/knowledge_gap_agent/utils/canonical.py) 中的 `canonical_json(value)` 使用四个固定条件：

- `sort_keys=True`：映射键按字典序输出；
- `separators=(",", ":")`：去掉非必要空白；
- `ensure_ascii=False`：中文保持 UTF-8 文本；
- `allow_nan=False`：`NaN`、正无穷和负无穷早拒绝。

`sha256_hex(value)` 对规范 JSON 的 UTF-8 字节计算 SHA-256。于是：

```text
{"b": 2, "a": 1}
        ↓ 规范化
{"a":1,"b":2}
        ↓ UTF-8 + SHA-256
稳定的 256 位摘要，以 64 个小写十六进制字符表示
```

稳定哈希不等于“所有变化都忽略”。键的输入顺序变化不影响哈希；字段值、字段集合或数组顺序变化通常会影响哈希。集合语义的字段必须先由业务层明确排序，例如环境哈希会分别排序三组块编号。`canonical_json` 不会擅自重排数组。

`RunConfig.config_hash` 的意义也是内容身份，而不是运行结果摘要。模型版本、温度、超时、提示词哈希、数据集版本、语料哈希和随机种子等会改变实验边界的字段都进入配置哈希；任务输出和延迟不进入配置哈希。

## Markdown 行级切块

[src/knowledge_gap_agent/corpus/chunking.py](../../src/knowledge_gap_agent/corpus/chunking.py) 的 `chunk_markdown(document, max_chars=1200)` 依次处理：

1. 把 `CRLF`、`CR` 统一为 `LF`；
2. 识别 1–6 级 ATX 标题，维护 `heading_path`；
3. 以空行结束普通段落，围栏代码中的伪标题仍属于正文；
4. 同一标题下尽量按完整段落组合；只有加入下一段会超过 `max_chars` 时才开新块；
5. 单段本身超过限制时保留整段，不做字符级硬切；
6. 为每块保留原始 `start_line`、`end_line`。

块正文先计算 `content_hash`。随后使用以下字段计算 `chunk_id`：

```text
source_id + heading_path + start_line + end_line + content_hash
```

因此，相同正文移动到别的行会保留相同 `content_hash`，但 `chunk_id` 会变化。这个取舍让引用既能判断“内容是否相同”，也能判断“证据来自文档的哪个位置”。对应边界案例在 [tests/corpus/test_chunking.py](../../tests/corpus/test_chunking.py) 中，包括围栏代码、跳级标题、超长单段、换行风格和重复正文。

## BM25 分词、IDF 与得分

### 确定性分词

[src/knowledge_gap_agent/retrieval/tokenizer.py](../../src/knowledge_gap_agent/retrieval/tokenizer.py) 不依赖外部分词模型：

- 连续中文生成相邻二元字组，例如“知识缺口”变为 `知识`、`识缺`、`缺口`；
- 单个汉字保留为单字词项；
- `[A-Za-z0-9_]+` 作为完整词项并转为小写；
- 标点和空白忽略。

这种方法牺牲了语义分词能力，换来固定输出、零模型依赖和可手算的回归基线。

### 公式

对词项 $t$ 和文档 $d$：

$$
\operatorname{idf}(t)=\ln\left(1+\frac{N-n_t+0.5}{n_t+0.5}\right)
$$

$$
\operatorname{score}(q,d)=\sum_{t\in q}\operatorname{idf}(t)
\frac{f(t,d)(k_1+1)}{f(t,d)+k_1\left(1-b+b\frac{|d|}{\operatorname{avgdl}}\right)}
$$

当前默认 `k1=1.5`、`b=0.75`。查询词项按首次出现去重；得分大于 0 的结果按 `(-score, chunk_id)` 排序，所以同分时仍有确定顺序。

### 两文档手算小例

沿用 [tests/retrieval/test_bm25.py](../../tests/retrieval/test_bm25.py) 的金丝雀数据：

```text
d_a = "apple apple banana"
d_b = "apple carrot carrot"
q   = "apple banana"
```

两篇文档长度都是 3，因此 `avgdl=3`，长度归一化项为 `1.5`。共有 `N=2` 篇文档：

- `apple` 出现在 2 篇中，`idf(apple)=ln(1.2)=0.1823215568`；
- `banana` 出现在 1 篇中，`idf(banana)=ln(2)=0.6931471806`。

对 $d_a$：

```text
apple 贡献 = 0.1823215568 × 2 × 2.5 / (2 + 1.5)
             = 0.2604593668
banana 贡献 = 0.6931471806 × 1 × 2.5 / (1 + 1.5)
             = 0.6931471806
总分         = 0.9536065474
```

对 $d_b$，只有一次 `apple` 命中，总分为 `0.1823215568`。实现返回的 `score` 应等于 `term_scores` 之和。

## 12×4 环境视图

候选集没有复制 48 份知识库。固定语料只保存一份，每个 `KnowledgeEnvironment` 用三个互斥编号集合描述视图：

- `visible_chunk_ids`：运行开始前可见的本地知识；
- `research_chunk_ids`：研究或检索后才可取得的证据；
- `excluded_chunk_ids`：该环境明确不可用的控制证据。

当前数据由 12 个 `base_question_id` 各派生 4 个环境，共 48 条候选：`local_sufficient`、`local_partial`、`outdated`、`conflict` 各 12 条。这里的“12×4”表示同一基础问题在四种受控知识条件下比较，不是把问题换 4 种说法。

`environment_hash` 绑定环境编号和三组排序后的块编号。环境校验还要求三组互斥，缺失主张不能被可见块支持，过时与冲突场景必须有相应的时效或冲突证据。当前候选分布与引用完整性由 [tests/benchmark/test_fixture_dataset.py](../../tests/benchmark/test_fixture_dataset.py) 验证。

## 运行信封与模型输入白名单

[src/knowledge_gap_agent/benchmark/validation.py](../../src/knowledge_gap_agent/benchmark/validation.py) 区分两个载荷。

`build_runtime_payload` 生成评测器使用的 runtime envelope，包含：

```text
case_id, base_question_id, question, environment_id, visible_chunk_ids
```

这些编号用于评测器关联环境与语料，但不能把整个信封原样交给决策模型。`build_model_input_payload` 重新校验 case、environment 与 chunk 后，只输出：

```text
question, visible_knowledge
```

模型看不到 case 编号、环境编号、块编号、类别、`need_research`、答案、必需主张、缺失主张、证据引用、复核状态和人工状态。可见块不存在、块编号重复或 case 与环境不配对时，公共入口在模型调用前早拒绝。

这种分层不是为了隐藏秘密。编号通常可枚举，不能依赖加密或盐值掩盖标签。真正的控制点是明确的数据白名单和物理分离的运行集、标签集、审计集。

## ReviewInput、ReviewRecord、独立复核与人工升级

[src/knowledge_gap_agent/benchmark/review.py](../../src/knowledge_gap_agent/benchmark/review.py) 把“待审内容”和“复核结论”分开：

- `ReviewInput` 是 Reviewer 实际看见的 case 白名单、三池块正文及相关主张，并携带 `review_target_hash`；
- `ReviewRecord` 保存 `decision`、问题、修改建议、证据引用、置信度、提示词与模型身份，以及同一个目标哈希。

case 中的 `annotation_reason`、`review_status`、`human_review_status` 不进入待审目标，因为 Reviewer 不应看到标注长推理，后两个字段本身又是复核派生状态。其他 Reviewer 可见字段、块正文、主张时效或冲突边发生变化时，哈希都会变化。

构造顺序是：

```text
可信 case + environment + chunks + claims
→ ReviewTargetInput（无哈希）
→ 规范 JSON + SHA-256
→ ReviewInput（带 review_target_hash）
→ 独立 Reviewer
→ ReviewRecord（回传相同哈希）
```

`ReviewInput` 自己会复算哈希；`apply_review_gate` 和冻结入口也会从当前可信语料重建目标，不能相信文件自报的哈希。旧记录即使 `case_id` 相同，只要目标内容变了也会被拒绝。

两轮复核保持独立历史：未修改的 40 条保留首轮记录，修改的 8 条使用第二轮记录。`reviews.jsonl` 必须逐字节等于这项规范合并。当前 48 条决策都是模型 `approve`；`requires_human_review` 仍会把以下候选升级为人工处理：

- 类别为 `outdated` 或 `conflict`；
- 模型决定为 `revise` 或 `reject`；
- Reviewer 置信度低于 `0.8`；
- `prior_rule_failure_count` 大于 0。

门禁只能写入人工 `pending` 或 `not_required`，不能写出人工批准。当前恰有 24 条人工 `pending`，正式冻结必须等待真实人工结论。

## 成功链

当前候选构造的成功链是：

```text
固定来源提交与内容哈希
→ 文本规范化和 Markdown 切块
→ 主张与证据双向关联
→ 12 个基础问题 × 4 个环境
→ 确定性结构、引用、互斥、泄漏校验
→ Reviewer 可见输入和目标哈希
→ 两轮独立复核的规范合并
→ apply_review_gate
→ 24 条 not_required + 24 条人工 pending
```

“成功”指候选数据和门禁状态可重建，不表示正式基准已经发布。

## 失败与早拒绝链

下面任一情况都会在进入后续阶段前停止：

```text
来源哈希不符
→ manifest 校验拒绝，不切块

环境三池重叠或 environment_hash 不符
→ KnowledgeEnvironment 构造拒绝

缺失主张被可见块支持、证据越界或引用不存在
→ validate_case / validate_dataset 返回问题

runtime envelope 含标签字段，或模型输入需要未知块
→ 泄漏测试或模型输入入口拒绝

ReviewRecord 的 review_target_hash 已陈旧
→ apply_review_gate 在改变状态前拒绝

高风险样本仍为人工 pending
→ freeze_benchmark(require_human_approval=True) 拒绝正式冻结
```

早拒绝的价值是保留责任边界：结构错误交给确定性规则，语义判断交给独立 Reviewer，高风险最终判断交给人。

## 代码与测试导航

按下面的顺序阅读，可以把数据身份、检索、泄漏控制和复核门禁串起来。

| 主题 | 源码入口 | 重点测试 | 观察点 |
|---|---|---|---|
| 规范 JSON 与哈希 | [src/knowledge_gap_agent/utils/canonical.py](../../src/knowledge_gap_agent/utils/canonical.py) 的 `canonical_json`、`sha256_hex` | [tests/utils/test_canonical.py](../../tests/utils/test_canonical.py) | 键顺序、紧凑 JSON、256 位摘要及其 64 字符十六进制表示 |
| 行级切块 | [src/knowledge_gap_agent/corpus/chunking.py](../../src/knowledge_gap_agent/corpus/chunking.py) 的 `chunk_markdown` | [tests/corpus/test_chunking.py](../../tests/corpus/test_chunking.py) | 标题路径、行范围、围栏代码、块身份 |
| 分词 | [src/knowledge_gap_agent/retrieval/tokenizer.py](../../src/knowledge_gap_agent/retrieval/tokenizer.py) 的 `tokenize` | [tests/retrieval/test_tokenizer.py](../../tests/retrieval/test_tokenizer.py) | 中文二元字组、英文小写、空输入 |
| BM25 | [src/knowledge_gap_agent/retrieval/bm25.py](../../src/knowledge_gap_agent/retrieval/bm25.py) 的 `BM25Index.build`、`search` | [tests/retrieval/test_bm25.py](../../tests/retrieval/test_bm25.py) | 手算分数、长度归一化、同分排序 |
| 环境与白名单 | [src/knowledge_gap_agent/benchmark/validation.py](../../src/knowledge_gap_agent/benchmark/validation.py) 的 `validate_case`、`build_runtime_payload`、`build_model_input_payload` | [tests/benchmark/test_validation.py](../../tests/benchmark/test_validation.py) | 三池语义、标签字段、模型输入字段 |
| 复核目标与门禁 | [src/knowledge_gap_agent/benchmark/review.py](../../src/knowledge_gap_agent/benchmark/review.py) 的 `build_review_input`、`apply_review_gate` | [tests/benchmark/test_review.py](../../tests/benchmark/test_review.py) | 可见字段、陈旧哈希、人工升级 |
| 冻结 | [src/knowledge_gap_agent/benchmark/freeze.py](../../src/knowledge_gap_agent/benchmark/freeze.py) 的 `freeze_benchmark` | [tests/benchmark/test_freeze.py](../../tests/benchmark/test_freeze.py) | 三文件分离、人工门禁、整体哈希 |
| 固定候选集 | [fixtures/benchmark/drafts.jsonl](../../fixtures/benchmark/drafts.jsonl) | [tests/benchmark/test_fixture_dataset.py](../../tests/benchmark/test_fixture_dataset.py) | 48 条分布、两轮合并、24 条人工队列 |

## 取舍与下一阶段边界

当前实现有意保持小而确定：二元字组便于复现，但不是高质量中文语义检索；BM25 只给出相关性排序，不判断知识是否充分；单一证据池加环境视图降低重复数据，却要求严格校验三池互斥；模型复核能发现语义问题，但不能替代人工终审。

下一阶段才实现最小 Runtime、动作循环、工具执行、Trace/Replay 与 E0 基线。本阶段不实现以下内容：

- 不根据 BM25 分数自动决定是否联网研究；
- 不调用外部模型或搜索接口；
- 不写回长期知识；
- 不报告任务成功率、成本下降或性能提升；
- 不创建阶段标签，也不生成正式冻结文件。

## 验收命令

在仓库根目录执行：

```powershell
uv run python -m pytest tests/learning/test_stage_01_materials.py -v
uv run python demo/01_config_trace.py
uv run python demo/02_bm25_retrieval.py
uv run python -m pytest -q
uv lock --check
git diff --check
```

两个 Demo 应正常退出；BM25 Demo 的两次输出应逐字节一致。测试通过只证明当前自动化契约成立，24 条人工 `pending` 仍然阻止正式冻结。
