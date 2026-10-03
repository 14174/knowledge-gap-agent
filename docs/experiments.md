# 实验记录

## 2026-10-03：人工退回后的语义修订与第三轮复核

### 目的与假设

检查人工发现的正文语义缺口是否被修正，并验证共享证据变更不会继续复用旧目标上的模型结论。本轮仅评估固定候选数据质量及审计流程，不测量智能体的任务成功率、检索收益、延迟或成本，也不能据此声称系统设计有效。

四条旧目标均保存为项目所有者的 `revise`；其中基础问题 01 的过时样本原本成立，因同组问题与共享证据修订而失效，不把它误报为同类语义缺陷。人工记录时间 `2026-10-03T15:23:34.049831+08:00` 表示首次规范落盘时间，不冒充原聊天消息时间。

### 构造与隔离

受控来源先单独提交为 `71b29bacd9e77b051a7e7b12fce710386d473dd9`，再固定其快照。基础问题 01 收紧到序列化规范与配置身份边界；第二条受控命题改为键排序、UTF-16 和允许非有限数值，使当前证据能够逐端裁决。基础问题 02 的当前主张明确选择 `tuple`，同时保留不可变列表子类的风险解释；其证据沿用既有固定来源。

旧基线由首轮 48 条输入和第二轮 8 条覆盖项还原。隔离准备模式只导出前后目标哈希不同的输入，得到 14 条：基础问题 01、02、12 各 4 条，基础问题 11 为 2 条。后两组因共享主张或受控证据受到影响；其余 34 条目标不变。

独立复核代理不继承本次讨论历史，只读取自包含提示词和这 14 条输入；另一独立代理检查正文与输出质量。输出记录模型标识 `gpt-6`、版本 `runtime-managed-undisclosed`，不虚构不可见的具体模型版本或采样配置。十四条均为 `approve`，最低置信度 `0.94`。这些置信度是复核模型自报值，不是经过统计校准的正确概率。

### 归档证据

| 文件 | SHA-256 |
| --- | --- |
| `human_review_history/round-1-reviews.jsonl` | `6c55d48662d157f8bf51eb6c6d34da4203f4ee68025acf80d10218592e82bcc5` |
| `reviewer_human_revision_prompt_v1.md` | `a04e118daa90003955c7e4b1354ea2878a664a0340b341b4c9144a4dbfe6bbb1` |
| `review_history/round-3-inputs.jsonl` | `7b54563bc191829928ede3e9354c3603b481e7ae9c795b162ef22f1e27df1ca2` |
| `review_history/round-3-reviews.raw.jsonl` | `dd96f45de9918d8e9e6d64faefe66a62c05f6987f158ecbcb12adf826f1801ac` |
| `review_history/round-3-reviews.jsonl` | `2c73c77b9b29b6ce75d4364d41516abae946e24092e2d7875da97d21433128e0` |

以上路径均相对于 `fixtures/benchmark/`。首次复核输出时间戳含七位小数，原复核代理另产六位小数规范副本；独立质量检查确认唯一变化是截断时间戳第七位，决策、理由、证据和置信度不变。首次原始字节与规范副本均保留，规范副本参与当前合并。

正式重建后，当前记录来自首轮 30 条、第二轮 4 条、第三轮 14 条。主代理逐字节核对前两轮四份归档与来源提交 `71b29ba` 中的版本相同，旧日志前 2,585 字节摘要不变。新增 14 条实施记录的实际落盘时间为 `2026-10-03T15:40:48.619512+08:00`，总日志为 16 条。

当前派生产物的实测摘要如下，不覆盖文末旧实验中的历史摘要：

| 文件 | SHA-256 |
| --- | --- |
| `fixtures/sources/manifest.json` | `da4337b7e70abca415619f7153e6aa70b071f536e87b621eeca8ab8ba469cccd` |
| `fixtures/corpus/documents.jsonl` | `e0a1f6e5ca19fd11caffdb0a5a7c6ff6e9d08de979a6f384717356599d2e9e56` |
| `fixtures/corpus/chunks.jsonl` | `ad06a276dbfccc96a4dec6e9c744b145d3d46d973dbc68fb9effdde3f291a273` |
| `fixtures/corpus/claims.jsonl` | `d1db71d21375bd6f0d4803912a08e0bbb42924b7ba7fffe21a5fa6ce23582f64` |
| `fixtures/benchmark/drafts.jsonl` | `fa609d8956cc8a840e89b644e53c5ebe873737c9b26a8e45ac3448c524981b6f` |
| `fixtures/benchmark/review_inputs.jsonl` | `4ea710c72256f614512ac160a2f8df737d99f2d337596e9d2157db8f09109234` |
| `fixtures/benchmark/reviews.jsonl` | `7126a563f690bf7385b345acfd8f7087ee4e8b57de2c28cf1eda6b7e2c591238` |
| `fixtures/benchmark/human_review_queue.jsonl` | `74be74151f879b7d0dcf415e7e0a9e86af9d43ba01f2f623f467df082c6274c8` |
| `fixtures/benchmark/change_log.jsonl` | `ecb7b48f968f931dc6382189f5de58c1f5c9d92ec457a749fcbf70fa9cb93d45` |
| `docs/阶段一人工终审清单.md` | `b9b92489064f7e1ee47b6d5c1afd682fbbd2c7a526c76c49c1a25417c2be2cfa` |

### 验收边界

第三轮全部通过且置信度不低于 `0.8` 才能重建。变更目标使用第三轮记录，其余目标保留原始轮次；旧日志前 2,585 字节保持不变，新增 14 条实施修订记录不是 14 条人工意见。新清单仍有 24 条高风险人工待审，不生成当前人工批准、正式冻结或阶段标签。

来源独立提交的验证为定向 4 项通过、全量 `614 passed, 1 skipped`；符号链接权限条件跳过。

最终静止版本由主代理独立执行：

```powershell
uv run python -m pytest tests/benchmark tests/learning -q
uv run python -m pytest -q
uv run python demo/01_config_trace.py
uv run python demo/02_bm25_retrieval.py
uv lock --check
git diff --check
```

专项为 `347 passed`，耗时 `279.86s`；全量测试为 `659 passed, 1 skipped`，耗时 `278.07s`。唯一跳过项仍为 Windows 符号链接权限条件。两个演示、锁文件与差异检查通过。另在临时副本执行正式构建与清单渲染，29 份夹具文件重建前后逐字节相同，清单摘要一致。

中途失败及处理也保留：一项旧文档测试将问题数量固定为两条，已迁移为四项真实问题且保留原检查；十一项非法日志测试发现错误消息缺少文件名，已补文件名、实际行号及原始异常链。新增直接调用诊断测试验证该行为，不再依赖异常栈恰好打印某行源码。两轮独立规格与质量审查均在修复后通过。

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
