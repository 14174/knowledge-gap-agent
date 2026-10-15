# 阶段三：从检索相关性到知识充分性

本阶段已展开，覆盖知识检索、模型充分性及其与评测的边界。先完成阶段二，能读懂一次模型请求与响应。

## 相关不等于够用

一个问题同时要求解释“冻结容器为什么选元组”和“如何保持数组输出”。检索到一段只讨论序列化的正文，分数再高也没有回答第一个要求。阶段一 BM25 演示已经可以显示命中主张，但那些主张属于离线评测标签，不能交给运行模型充当答案提示。

本次设计审查明确修正了旧计划中“把任务所需主张给充分性判断”的设想。运行时改为只提供问题与证据，由模型自行拆解缺口。分类准确率需要和最终答案质量一起检查。

## 演示和调用链

```powershell
uv run python demo/05_knowledge_provider.py
uv run python demo/06_sufficiency_gate.py
uv run python -m pytest tests/knowledge tests/skills -q
```

05 写入经过固定响应验证的条目、关闭数据库、重新打开并检索；06 输出 `enough`、`partial`、`missing` 及一个低置信度例。它们是固定响应工程演示，不是分类效果实验。

```text
问题 → SQLiteKnowledgeProvider.search
 → BM25Index.search → KnowledgeHit.as_evidence
 → assess(问题, 证据, 模型)
 → needs_research
 → 需要时研究 / 否则作答
```

源码顺序：先看 [检索器](../../src/knowledge_gap_agent/retrieval/bm25.py) 的 `BM25Index.build/search`，再看 [提供器](../../src/knowledge_gap_agent/knowledge/store.py) 的 `search/as_evidence`，最后看 [充分性](../../src/knowledge_gap_agent/knowledge/sufficiency.py) 的 `assess` 和 `SufficiencyDecision.needs_research`。建库验证与写回属于阶段四，候选技能留给阶段五。

## 算法与字段

沿用阶段一的 BM25，中文用确定性二元字组、英文用词项。对查询词项逐个计算：

```text
IDF(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
score(q,d) = Σ IDF(t) f(t,d)(k1+1)
             / [f(t,d)+k1(1-b+b|d|/avgdl)]
k1 = 1.5，b = 0.75
```

同分按知识编号稳定排序。分数只衡量词项相关性；充分性判断不能把某个固定分数直接视作完整知识。

判断字段包括三类标签、预测缺少要点文字、陈旧证据引用、冲突证据引用、置信度和理由。`missing_claims` 虽沿用字段名，但值是模型预测的文字，不是数据集主张编号。原始响应附在结果里便于评测追溯。

研究触发规则固定为：

```text
label != enough
或 confidence < 0.8
或 missing_claims 非空
或 stale_ids 非空
或 conflict_ids 非空
```

非法 JSON、标签与缺口不一致、引用没有见过的编号会安全降级为 `partial`、置信度零，理由明确标记输出无效，并保留原响应。模型不能自行填充审计响应字段。

## 两条可观察路径

足够例：问题的所有要求都有证据，模型输出 `enough`、空缺口和空异常引用、置信度 0.9；门禁不强制研究。

失败例：模型输出 `enough`，却同时指出证据过期；这在结构上矛盾，结果降级为需要研究。另一种情况是标签 `enough`、置信度 0.7，即使结构合法也触发研究。

低置信度触发研究并不保证答案变好。门槛调高可能同时增加真阳性与假阳性，因此必须同时观察搜索次数、错误充分率和任务通过率。

## 评测公式与边界

把“需要研究”视为正类：

```text
Precision = TP / (TP + FP)
Recall = TP / (TP + FN)
F1 = 2TP / (2TP + FP + FN)
FalseSufficientRate = FN / (TP + FN)
```

零分母输出缺失值，不假装为满分。分类真值只由评测器读取。运行失败不会被悄悄归成“本地充分”，也不能从任务成功率分母中删除。

固定教程第八章区分临时历史与可持久检索记忆；本项目把这一区别落实为循环中的观察历史与 SQLite 条目。学完后应能解释：某块分数很高时，为什么仍可能必须研究？请用问题要求、证据缺口和门禁字段重走一次流程。
