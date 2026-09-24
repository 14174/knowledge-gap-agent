# 第二天候选基准构造说明

## 1. 范围与状态

本批数据是 `day2-draft-v0.1` 候选集，不是正式冻结集。它包含 8 份固定来源、316 个确定性 Markdown 块、48 条主张、48 条候选样本和 48 条独立 Reviewer 输入。首轮 Reviewer 原样输出为 42 条 `approve`、6 条 `revise`；质量审计把实际修订范围扩为 base-02、base-08 共 8 条，第二轮对这 8 条全部 `approve`。当前 `reviews.jsonl` 由首轮未变化的 40 条与第二轮 8 条真实记录合并，最终 48 条模型复核均为 `approve`；24 条高风险类别进入 `human_review_queue.jsonl`，仍待真实人工审核。`change_log.jsonl` 仍只有两组非人工修订；尚未生成正式 `runtime`、`labels` 或 `audit` 文件，也没有人工批准结论。

构建时间统一固定为 `2026-09-24T00:00:00+08:00`。来源文本先规范化为 UTF-8、LF、无行尾空白且恰有一个终止换行，再写入仓库内 `fixtures/sources/raw/`。后续重建只读取这些 raw 副本，不访问网络或外部克隆。

## 2. 来源选择

| 来源 | 固定提交 | 选择理由 |
| --- | --- | --- |
| `docs/实验合同.md` | `19e13d048cf0e6ba11695f4d6dd954cb8a364ebb` | 提供配置身份、基准真值和知识缺口指标定义。 |
| `docs/AI_CODING_GUIDE.md` | `55e1c2f40356558c0cfafcb639830201000af20f` | 提供 TDD、双级审查、模块边界、数据隔离和人工门禁规则。 |
| `docs/decisions.md` | `55e1c2f40356558c0cfafcb639830201000af20f` | 提供冻结容器采用 `tuple` 的决策与理由。 |
| `fixtures/sources/controlled/benchmark-distractors.md` | `a866aee6b000331ba2fa0e4079b3c8b902e52e20` | 只提供可验证的过时与冲突控制变量，不代表真实工程建议。 |
| `Agent-Learning-Hub/README.md` | `dddf777dde6788228136862f270203424a28efbc` | 提供从可运行作品到评估、可观测性与安全的学习路线。 |
| `hello-agents` 第 7 章 | `5caceca4e4c9a3d25cd14627881436953f4d6912` | 提供 Agent 框架消息契约与历史管理证据。 |
| `hello-agents` 第 8 章 | `5caceca4e4c9a3d25cd14627881436953f4d6912` | 提供记忆分层、文档处理和 RAG 检索流程证据。 |
| `hello-agents` 第 12 章 | `5caceca4e4c9a3d25cd14627881436953f4d6912` | 提供多维评测和人工质量验证证据。 |

外部教程仅选择指定中文章节，不使用前三章的概念介绍。`manifest.json` 同时记录仓库、提交固定的网址、原始相对路径、raw 本地路径、抓取时间和规范化内容哈希。

### 2.1 远端固定网址核验

分支 `codex/day2-corpus-benchmark` 已推送至 `origin`。在 `2026-09-24T18:52:44+08:00` 使用只读 HTTP GET 核验三条固定网址，均返回 `200`。这些路径均为 ASCII，无需额外百分号编码。测试只校验网址包含固定提交与原始相对路径，不在本地或离线测试中发起网络请求。

| 来源 | 固定网址 | HTTP 状态 |
| --- | --- | --- |
| AI Coding 工程规范 | `https://github.com/14174/knowledge-gap-agent/blob/55e1c2f40356558c0cfafcb639830201000af20f/docs/AI_CODING_GUIDE.md` | `200` |
| 设计决策 | `https://github.com/14174/knowledge-gap-agent/blob/55e1c2f40356558c0cfafcb639830201000af20f/docs/decisions.md` | `200` |
| 受控基准干扰证据 | `https://github.com/14174/knowledge-gap-agent/blob/a866aee6b000331ba2fa0e4079b3c8b902e52e20/fixtures/sources/controlled/benchmark-distractors.md` | `200` |

## 3. 十二个基础主题

每个基础问题恰有两条来自真实项目或教程块的当前必需主张。每个主题另有两条只来自受控文档的 A、B 命题。标题与正文不携带类别标签；A、B 对同一决策维度给出互斥规则，其中 A 的失效时间固定为 `2026-09-23T23:59:59+08:00`。

| 编号 | 主题 | 当前证据重点 |
| --- | --- | --- |
| 01 | 规范 JSON 哈希 | 映射键排序与配置身份变量。 |
| 02 | 冻结容器 | 自定义不可变 `list` 子类的不足、内部 `tuple` 与 JSON 数组兼容。 |
| 03 | 测试驱动开发 | 先观察红灯及用回归测试固定缺陷。 |
| 04 | 双级审查 | 规格先于质量，且审查角色独立。 |
| 05 | 模块边界 | 语料职责边界与避免重复状态机。 |
| 06 | Agent 框架消息契约 | 四类角色消息与历史上下文。 |
| 07 | 记忆分层 | 会话工作记忆与长期语义记忆。 |
| 08 | 检索流程 | 完整 RAG 与异构文档统一转 Markdown 后的处理。 |
| 09 | 评测指标 | 知识缺口指标与任务相关的多维评测。 |
| 10 | 评测数据隔离 | 运行、标签、审计物理隔离与正式冻结门禁。 |
| 11 | 学习路线 | 可运行项目阶梯与评估、可观测性阶段。 |
| 12 | 人工门禁 | 高风险升级条件与人工最终把关。 |

## 4. 四环境派生矩阵

记 `C1`、`C2` 为两条当前必需主张的证据块，`A`、`B` 为本主题的受控互斥命题，`NR` 为下一主题的无关当前块，`NA`、`NB`、`NX` 为跨主题受控块。奇数主题缺失 `C1`，偶数主题缺失 `C2`；`CK` 表示另一条已知当前块。

| 环境 | 可见池 | 研究池 | 排除池 | 缺失主张 | `need_research` |
| --- | --- | --- | --- | --- | --- |
| `local_sufficient` | `C1, C2, NA, NB` | `NR` | `NX` | 空 | `false` |
| `local_partial` | `CK, NR, NA, NB` | `CM` | `NX` | `CM` 对应主张 | `true` |
| `outdated` | `CK, NR, A, NA` | `CM` | `B` | `CM` 对应主张 | `true` |
| `conflict` | `CK, NR, A, B` | `CM` | `NX` | `CM` 对应主张 | `true` |

四类环境都具有 4 个可见块、1 个研究块、1 个排除块和 2 个可见受控块。`NR`、`NA`、`NB`、`NX` 均来自其他主题，不支持本题必需主张。A 与 B 互相冲突，并与本主题交替选定的当前裁决主张建立冲突边。这样，过时环境具有“失效可见证据 + 研究池当前更新”，冲突环境具有“两条受控可见冲突 + 研究池当前裁决”，同时不能通过池大小或受控块数量恢复类别。

### 4.1 十二组互斥语义

| 主题 | 命题 A | 命题 B | 互斥理由 |
| --- | --- | --- | --- |
| 规范 JSON 哈希 | 唯一策略保留字典原始顺序且禁止排序。 | 唯一策略同时排序映射键和所有数组。 | 同一输入只能采用一种唯一序列化策略。 |
| 冻结容器 | 唯一容器是普通 `list`。 | 唯一容器是自定义不可变 `list` 子类。 | 两种规范都明确禁止另一种容器。 |
| 测试驱动开发 | 实现完成后才允许编写测试。 | 测试必须在实现前写好。 | 测试相对实现的先后顺序相反。 |
| 双级审查 | 只允许原实现者做一次合并自审。 | 必须由独立角色先质量审查再规格审查。 | 审查角色数量和阶段顺序不能同时成立。 |
| 模块边界 | 研究决策唯一归 `benchmark`。 | 研究决策唯一归 `corpus`。 | 同一职责不能同时有两个唯一所有者。 |
| 消息契约 | 唯一契约是包含全部上下文的自由字符串。 | 唯一契约只保留最新用户文本。 | 输入是否包含系统、历史和工具信息相反。 |
| 记忆分层 | 唯一介质是无限会话列表。 | 唯一介质是外部向量数据库。 | 两种规则都禁止另一种介质。 |
| 检索流程 | 唯一路径是完整原始文件直接进入提示词。 | 唯一路径是最高分块直接成为最终答案。 | 数据准备和回答路径是两个互斥流程。 |
| 评测指标 | 唯一判据是任务准确率。 | 唯一判据是平均响应延迟。 | 同一次总体判定不能同时只有两个不同唯一指标。 |
| 评测数据隔离 | 正式冻结只信任调用方手填的人工审核状态。 | 正式冻结忽略人工审核状态并无条件自动通过。 | 一条要求读取手填状态，另一条禁止读取且固定通过；二者都排斥重新计算门禁。 |
| 学习路线 | 完成全部理论前禁止运行示例。 | 只允许复制运行，禁止学习理论与结构。 | 一条要求理论先行，另一条禁止理论学习。 |
| 人工门禁 | 唯一条件是两个模型结论一致。 | 唯一条件是置信度不低于 `0.8`。 | 两个规则都声明另一信号不参与判断。 |

## 5. Labeler 配置

本次 Labeler 是确定性脚本 `scripts/build_day2_fixtures.py`，没有调用外部模型。模型标识、温度、提示词版本和提示词哈希均不适用；构造逻辑由版本控制中的脚本、固定来源哈希和测试共同标识。

- Markdown 切块使用项目 `chunk_markdown` 默认上限 `1200` 字符，只在段落边界拆分。
- `token_terms` 使用项目确定性中文二元字组与英文词项分词器。
- 主张先建立到证据块的映射，再通过 `model_copy(update=...)` 回填块的 `claim_ids` 与 `token_terms`。
- 每行草稿严格为 `{"case": ..., "environment": ...}` 的规范 JSON。
- 所有 case 当前为 `draft_status=validated`、`review_status=approved`。24 条 `local_sufficient`、`local_partial` 为 `human_review_status=not_required`；12 条 `outdated` 与 12 条 `conflict` 为 `human_review_status=pending`。这些状态来自可信 `apply_review_gate`，不代表人工通过。
- `build_runtime_payload` 只构造供评测器关联数据的冻结信封，允许保留不透明关联编号；该信封不得原样传给决策模型。
- `build_model_input_payload` 采用独立白名单，只输出问题与按环境顺序解析的可见知识正文；入口重新验证 case、environment 和 chunk，校验 case/environment 配对，并在模型调用前拒绝未知或重复块引用。
- `review_inputs.jsonl` 由 Pydantic 白名单确定性生成，包含待审 case、环境三池正文和相关主张证据，不包含 `annotation_reason`、`review_status`、`human_review_status`、Labeler 长推理或任何复核结论。
- 每条 Reviewer 输入的 `review_target_hash` 直接取自同一条无哈希 Reviewer 白名单输入的规范 JSON。它绑定结构化 case、三池展开后的块正文/来源/标题/主张关联，以及相关主张的陈述、时效、冲突与证据映射；明确排除 `annotation_reason`、`review_status`、`human_review_status`。非空 `reviews.jsonl` 在任何写盘前以当前可信语料重建并逐条核对，陈旧结果会早拒绝且保留原文件。

## 6. 规则校验

脚本在写盘前调用 `validate_dataset`，测试再独立验证以下条件：

- 恰有 12 个基础问题，每个派生四类环境，共 48 条；
- 所有 Pydantic 模型可重新解析，样本、环境和来源编号唯一；
- 三个环境池两两互斥，所有引用存在；
- 每条必需主张都有 case 证据，主张与块的引用双向一致；
- `local_partial` 的缺失集合是非空真子集，且缺失证据只在研究池；
- 过时与冲突环境满足现有时效和冲突边定义；
- `allowed_source_ids` 覆盖所有 case 证据来源；
- case 与 environment 使用内容派生的 16 位十六进制不透明编号，不含环境类别或研究提示；
- 四类环境的可见池、研究池、排除池和可见受控块数量分布完全相同，奇偶主题交替缺失 `C1` 与 `C2`，基于编号后缀、池大小、受控块数量或固定缺失位置的朴素规则不能完整恢复类别；
- 24 条当前主张分别由表驱动的语义标记契约核对原始证据文本；12 组受控命题分别用同一决策维度上的 A、B 极性标记核对互斥语义，不只依赖 `conflicts_with` 元数据；
- `build_runtime_payload` 不包含 `LABEL_FIELDS`，但其编号只用于评测器关联；即使攻击者公开枚举四个内部槽位并从信封编号恢复槽位，模型输入也不接收这些编号；
- 模型输入恰含问题和 4 条可见知识正文，不含研究池、排除池、样本/基础问题/环境/块编号、环境类别名或 `need_research` 提示；
- 模型输入公共入口会拒绝错误的 case/environment 配对、保留旧哈希的篡改 chunk 和空问题 case；
- 48 条 Reviewer 输入与草稿一一对应，三池正文可用、规范 JSON 稳定且无 `annotation_reason`；
- 每条磁盘 Reviewer 输入通过 `ReviewInput.model_validate_json` 自校验；问题、块正文、主张陈述或哈希任一被改写都会拒绝；
- ReviewRecord、复核门禁和冻结路径均从可信 chunks/claims 重建 Reviewer 实际可见输入；问题、答案键、类别、`draft_status`、环境池、块正文或相关主张变化会使旧复核失效，三个明确排除字段不改变哈希；
- Reviewer 输入字段集合与 case/environment/chunk/claim 模型字段集合逐项核对，未显式分类的新字段会早拒绝；`evidence_refs` 只允许落在对应环境三池并集，受控过时/冲突块可以被引用，环境外块拒绝；
- 当前 reviews 必须恰有 48 个唯一 case ID 并与当前草稿集合精确一致；每条都通过可信 `apply_review_gate` 重算目标与证据边界，partial、extra 或 stale 集合在任何产物写盘前拒绝；
- 人工队列只包含门禁后 `human_review_status=pending` 的 24 条高风险候选，并保留类别、目标哈希、触发原因、真实模型决策、置信度和提示词版本，不包含人工批准字段；
- 清单校验无错误，所有 JSONL 使用规范 JSON；
- 无外部来源重跑后，所有生成文件字节不变。

## 7. Reviewer 隔离与人工门禁

独立 Reviewer 只接收 `review_inputs.jsonl` 中的基础问题、环境三池正文、主张、证据和结构化草稿，不接收 `annotation_reason`、`review_status`、`human_review_status` 或 Labeler 的隐藏推理文本。后两个状态是复核及人工门禁输出。Reviewer 返回的 `review_target_hash` 必须来自对应输入。脚本保留每条复核的真实轮次、时间、置信度和提示词身份，不把模型结论写成人工批准。

### 7.1 首轮复核修订

首轮输入与 Reviewer 原输出分别原样归档为 `review_history/round-1-inputs.jsonl` 和 `round-1-reviews.jsonl`，字节哈希固定为 `b5949208d2b4e0e976015c720d9e04de985e6678431f75bf760faa600b6517a8`、`7a112d7125d006f3050bbda1c0e941871c62a99999cb0e1c88fc28b5c1890147`。复核提示词版本为 `day2-benchmark-review-v1`。构建与测试均实际读取 `reviewer_prompt_v1.md` 原始字节并计算 SHA-256，结果必须为 `5f1f17ef7e6ee0c5f9ca7ebabcb560faca51b23763501e94b27a4fd9c53399b7`，且必须与首轮 reviews 和两条修订记录的 `prompt_hash` 一致。

- base-02 的问题新增三个明确子问：自定义不可变 `list` 子类为何不足、为何选择 `tuple`、如何保持 JSON 数组兼容。普通 `list` 不作为独立子问，避免超出现有两条必需主张的直接证据边界。
- base-08 的问题同时要求完整 RAG 流程，以及异构文档为何、如何统一转为 Markdown 并进入后续分块、向量化和检索。
- 原 Reviewer 标记 6 条 `revise`；质量审计补充两组的 `local_sufficient`，实际修订为两个基础问题各 4 条，共 8 条。只改问题及由问题参与计算的目标哈希，来源、claims、证据、case ID 和 environment ID 均不变。
- 两条 `change_log.jsonl` 记录的 `actor` 是独立 Reviewer 与质量审计，`human_approved=false`。本轮不是人工终审，修订后 48 条输入仍需独立复审。
- `change_log.jsonl` 是版本化非空夹具，初始化只允许通过受审提交或人工流程完成，不属于构建器。构建器绝不创建、初始化或写入该文件；它在其他产物写盘前只读验证精确前缀、终止 LF 和所有后续行均为规范 JSON 对象。缺失或零字节视为损坏，前缀后的人工追加记录归人工流程所有并逐字节保留。

### 7.2 第二轮复核与模型门禁

第二轮只复核修订后的 8 条输入。输入原始行和 Reviewer 原输出分别归档为 `review_history/round-2-inputs.jsonl`、`round-2-reviews.jsonl`，SHA-256 为 `4351eebc1cdb6c2391c3c63c5c1e0ae981e1895f6f9f10d9fa17090b716caea3`、`94ae44ab604261c580d0705ac7615183810dfd38b782eca1b9aaa6b8759bf85d`。提示词 `reviewer_revision_prompt_v1.md` 的原始字节 SHA-256 为 `6bd78ec097255e1334ff6829912025ace6060906b04bcaef775103d354baf95f`；8 条记录均使用 `day2-benchmark-rereview-v1`，全部 `approve` 且置信度不低于 `0.8`。

当前 `reviews.jsonl` 不是任意一组结构合法、目标哈希匹配的 ReviewRecord，而是唯一的归档合并：修订 8 条必须逐对象取第二轮原记录，其余 40 条必须逐对象取首轮原记录，再按 `case_id` 排序并写成规范 JSONL。构建器现场校验两份提示词原始字节哈希，从两轮归档加载记录并重建预期字节；非空 `reviews.jsonl` 只有与该预期逐字节一致时才进入 `apply_review_gate`。因此提示词身份、模型身份、复核时间、结论、置信度、环境内证据引用、顺序或 JSON 格式任一漂移都会在写盘前拒绝。若 reviews 为空，则草稿保持 `pending` 且人工队列为空。

Reviewer 完成后，所有 `outdated` 和 `conflict` 样本、置信度低于 `0.8` 的样本、`revise`、`reject` 或曾经规则失败的样本都必须进入人工审核。自动阶段只能把人工状态改为 `pending` 或 `not_required`，不得写入人工 `approved`。人工修改必须追加到 `change_log.jsonl`，不得覆盖旧记录。

## 8. 重建与哈希

首次从已核验的只读克隆写入 raw 副本：

```powershell
uv run python scripts/build_day2_fixtures.py --seed-source-root <固定只读克隆根目录>
```

此后离线重建与验证：

```powershell
uv run python scripts/build_day2_fixtures.py
uv run python -m pytest tests/benchmark/test_fixture_dataset.py -v
Get-FileHash -Algorithm SHA256 fixtures/sources/manifest.json,fixtures/corpus/documents.jsonl,fixtures/corpus/chunks.jsonl,fixtures/corpus/claims.jsonl,fixtures/benchmark/drafts.jsonl,fixtures/benchmark/review_inputs.jsonl,fixtures/benchmark/reviews.jsonl,fixtures/benchmark/human_review_queue.jsonl,fixtures/benchmark/change_log.jsonl,fixtures/benchmark/review_history/round-1-inputs.jsonl,fixtures/benchmark/review_history/round-1-reviews.jsonl,fixtures/benchmark/review_history/round-2-inputs.jsonl,fixtures/benchmark/review_history/round-2-reviews.jsonl
```

本次构建的文件哈希为：

| 文件 | SHA-256 |
| --- | --- |
| `fixtures/sources/manifest.json` | `526f7a6ea4f49a7f8720c91dded5d6eccd8a72ad24676dd426957c536ea68262` |
| `fixtures/corpus/documents.jsonl` | `7b1f07d877ade7d0b1090c3ce39d9710fa2085f60b3f04dad2faeb1a614a4dd5` |
| `fixtures/corpus/chunks.jsonl` | `91eb2c7272286eff9eaa641a51e07ad6ff597f639d4f170d903644852429bcd7` |
| `fixtures/corpus/claims.jsonl` | `d59426b529d632ca4036a04172f1b72077e471b31613f4761bfd7031732c4666` |
| `fixtures/benchmark/drafts.jsonl` | `b101467a9da808f4e630965154c14293a22149e0f7326b7cb1f252f882847d55` |
| `fixtures/benchmark/review_inputs.jsonl` | `d7a734e4b9b23e8c0977f47f3491efd63776ecd160a2e02a4886c40191e20b10` |
| `fixtures/benchmark/reviews.jsonl` | `6ca3d1735e74ea0afca0bbe9a18e0bb8119dddfb6b6c40168aa9e3c9d819705e` |
| `fixtures/benchmark/human_review_queue.jsonl` | `d06cb65dc173eeaa9f10c9d250b5991b8848004e39fcdb42500baf333c7279ed` |
| `fixtures/benchmark/change_log.jsonl` | `5a5c0ec55530ee97e1ccd440994388139a4b6c82e0270a4cc0edac90d46dfa02` |
| `fixtures/benchmark/review_history/round-1-inputs.jsonl` | `b5949208d2b4e0e976015c720d9e04de985e6678431f75bf760faa600b6517a8` |
| `fixtures/benchmark/review_history/round-1-reviews.jsonl` | `7a112d7125d006f3050bbda1c0e941871c62a99999cb0e1c88fc28b5c1890147` |
| `fixtures/benchmark/review_history/round-2-inputs.jsonl` | `4351eebc1cdb6c2391c3c63c5c1e0ae981e1895f6f9f10d9fa17090b716caea3` |
| `fixtures/benchmark/review_history/round-2-reviews.jsonl` | `94ae44ab604261c580d0705ac7615183810dfd38b782eca1b9aaa6b8759bf85d` |
