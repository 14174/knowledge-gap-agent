# Knowledge-Gap-Aware Self-Evolving Agent Harness 项目计划

> 状态：设计已确认，尚未形成实现与实验结论。本文中的 `TBD`、`XX` 和空白表格均为待测项。

## 1. 项目背景

常见知识型 Agent 会在本地检索、Web Search、工具调用和回答生成之间做串联，但通常没有明确回答两个问题：

1. 本地知识是否足以支持当前结论，什么情况下必须继续研究？
2. 一次任务中的成功路径、失败原因和用户纠正，如何经过验证后影响未来任务？

本项目把这两个问题拆成两条相互独立但共享 Trace 与 Evaluation 的演化闭环：

- Knowledge Evolution 处理“知道什么”；
- Skill Evolution 处理“怎么做”。

目标不是一次性堆叠 Planner、RAG、Multi-Agent 和 MCP，而是建立最小基线，再用可复现实验决定哪些 Harness 策略值得进入默认架构。

## 2. 目标与非目标

### 2.1 目标

- 自研最小 Agent Runtime，掌握 Agent Loop、State、Session、Context、Tool Execution、Trace 与 Recovery。
- 让 Agent 显式判断本地知识是否充分，根据缺口触发定向 Web Research。
- 对研究证据进行来源、时效、引用和冲突检查，通过 Gate 后再写入长期知识。
- 从历史 Trace 与 Eval Feedback 中提炼 Candidate Skill，通过任务评测和回归门禁后再 Promotion。
- 建立覆盖 Outcome、Trajectory、Knowledge、Skill 与 Cost 的评测体系。
- 所有架构结论都能追溯到固定配置、Trace、实验结果和消融对照。

### 2.2 非目标

- 第一版不追求通用自治 Agent，也不支持任意高风险自动操作。
- 第一版不修改 LLM Wiki 内核，只通过 Provider/Adapter 接入。
- 第一版不默认采用 Multi-Agent。它是待验证假设，不是卖点前提。
- 不自己实现模型服务、MCP 协议、数据库驱动、搜索引擎或 tokenizer。
- 不在实验完成前声明任何成功率、成本或性能提升。

## 3. 总体架构

```text
                         User Task
                             │
                             ▼
                     Agent Runtime
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
       Context Manager    Tool Layer      Trace Store
              │              │              │
              │       ┌──────┼──────┐       │
              │       ▼      ▼      ▼       │
              │     Wiki    Web    Files     │
              │                              │
              ├──────── Knowledge Loop ──────┤
              │                              │
              └───────── Skill Loop ─────────┘
                             │
                             ▼
                    Evaluation System
```

原则：

```text
LLM != Agent
Agent != Harness
Harness != Application
```

Research Agent 是 Harness 上的第一个复杂 workload。LLM Wiki 是长期知识后端，不承担 Runtime 的全部职责。

## 4. 模块划分

| 模块 | 职责 | 主要输入 | 主要输出 |
|---|---|---|---|
| `runtime` | Agent Loop、状态转换、终止、重试、恢复 | Task、State、Context | Action、Observation、Final Result |
| `context` | 信息选择、Token Budget、Compaction | State、History、Knowledge、Evidence | Model Context |
| `planner` | 复杂度判断、Plan-Execute、Replan | Task、State | Plan、Next Step |
| `tools` | 注册、Schema 校验、执行、错误归一化 | Tool Call | Tool Observation |
| `knowledge` | 检索、充分性判断、研究、验证、沉淀 | Query、Retrieved Knowledge | Evidence、Knowledge Entry |
| `skills` | 经验提炼、候选管理、评测、版本与发布 | Trace、Eval Feedback | Candidate/Active Skill |
| `tracing` | Event、Trace、Replay、审计 | Runtime Events | Trace Record、Replay Input |
| `eval` | Benchmark、Judge、指标、回归门禁 | Task、Trace、Result、Skill | Scores、Gate Decision |
| `agents` | Research workload 及后续实验角色 | Task、Harness Services | Report / Result |
| `app` | CLI 与配置入口 | User Input、Config | Run、Eval、Replay 命令 |

建议目录：

```text
runtime/       loop.py state.py session.py lifecycle.py
context/       manager.py selector.py compactor.py
planner/       router.py planner.py executor.py
tools/         registry.py executor.py schemas.py mcp.py
knowledge/     provider.py llm_wiki.py sufficiency.py research.py verification.py consolidation.py
skills/        store.py distiller.py candidate.py evaluator.py promotion.py
tracing/       event.py store.py replay.py
eval/          benchmark.py evaluator.py judge.py metrics.py regression.py
agents/        research.py reviewer.py reporter.py
app/           cli.py config.py
```

目录只是模块边界草案；在接口稳定前不做过早抽象。

## 5. 核心接口

### 5.1 KnowledgeProvider

Harness 只依赖统一知识接口：

```python
class KnowledgeProvider(Protocol):
    def search(self, query: str, *, top_k: int) -> list[KnowledgeHit]: ...
    def read(self, knowledge_id: str) -> KnowledgeEntry: ...
    def related(self, entity: str) -> list[KnowledgeHit]: ...
    def write_candidate(self, entry: KnowledgeCandidate) -> str: ...
    def promote(self, candidate_id: str) -> KnowledgeEntry: ...
```

第一版实现 `LLMWikiProvider`。后续可增加普通 RAG Provider 作为对照，不让 Runtime 感知后端细节。

### 5.2 Tool

```python
class Tool(Protocol):
    name: str
    description: str
    input_schema: dict

    def execute(self, arguments: dict, context: ToolContext) -> ToolResult: ...
```

Tool Executor 负责参数校验、超时、重试、错误分类与 Observation 归一化。Tool 本身不直接修改 Agent State。

### 5.3 Evaluator

```python
class Evaluator(Protocol):
    def evaluate(self, case: EvalCase, run: RunResult) -> EvalReport: ...
```

确定性指标优先使用程序计算；开放式报告才使用 LLM Judge，并保留 Judge 配置和原始理由。

### 5.4 Skill

每个 Skill 至少保存：

```text
skill_id
name
version
status: candidate | validated | active | retired | rejected
applicability
procedure
source_trace_ids
created_at
previous_version
eval_config_hash
eval_score
regression_score
usage_count
success_count
failure_count
```

## 6. State、Session 与长期记忆

三者必须分离：

- State：单个任务正在变化的状态，如计划、消息、观察、证据、当前步骤和终止原因。
- Session：跨多个 Task 的会话容器，保存任务索引、配置和会话级引用。
- Long-term Memory：跨 Session 的 Knowledge Store 与 Skill Store。

第一版 State 使用 Pydantic 或 dataclass；Session、Trace 和元数据使用 SQLite；大文本与导出结果可保存为文件并在 SQLite 中记录引用。暂不引入 Redis、Kafka 或分布式数据库。

## 7. Knowledge Evolution 闭环

```text
Knowledge Retrieval
        ↓
Knowledge Sufficiency
   ├─ Enough  ─────────────────────────→ Answer
   ├─ Partial ─→ Targeted Web Research ─┐
   └─ Missing ─→ Deeper Web Research ───┤
                                        ↓
                              Evidence Verification
                                        ↓
                             Knowledge Consolidation
                                        ↓
                                  Candidate Entry
                                        ↓
                                Knowledge Write Gate
                                        ↓
                                     LLM Wiki
```

### 7.1 Sufficiency 输出

第一版采用结构化 LLM 判断，不训练分类器：

```json
{
  "label": "partial",
  "missing": ["最新实验结果", "直接来源"],
  "stale": [],
  "conflicts": [],
  "confidence": 0.73,
  "reason": "本地条目缺少可核验的近期证据"
}
```

后续对比 Rule、LLM Judge 与 Small Classifier。重点控制 False Negative，因为“误判为充分”会让系统基于残缺知识直接回答。

### 7.2 Web Research

Research Plan 由具体缺口驱动，不允许无目的扩展搜索。每个 Evidence Item 记录 URL、标题、作者/机构、发布时间、抓取时间、引用片段、支持的 Claim、来源类型和内容哈希。

### 7.3 Evidence Verification

最小检查项：

- 是否优先使用论文、官方文档、标准、原始数据等直接来源；
- 时间敏感信息是否满足任务时效要求；
- 关键 Claim 是否有足够来源支持；
- 多来源是否真正独立；
- 引用是否能支持对应结论；
- 新证据与本地知识是否冲突；
- 无法解决的冲突是否在答案中显式保留。

### 7.4 Knowledge Consolidation

写入长期知识前完成去重、Claim-Evidence 对齐、来源记录、有效期与冲突标注。研究报告不是直接写入内容；系统先提炼可复用知识单元，再进入 Candidate Entry 和 Write Gate。

## 8. Skill Evolution 闭环

```text
Trace
  ↓
Evaluation
  ↓
Failure Attribution / Success Pattern
  ↓
Experience Distillation
  ↓
Candidate Skill
  ↓
Evaluation Gate + Regression Gate
  ├─ pass ─→ Validated ─→ Active ─→ Runtime Retrieval
  └─ fail ─→ Reject 或 Revise
```

### 8.1 Experience Distillation

候选经验只来自可定位 Trace：成功路径、重复失败、恢复动作、用户纠正或评测反馈。Distiller 输出适用条件、步骤、禁止条件、失败处理和来源 Trace，不生成无依据的“最佳实践”。

### 8.2 Gate

Candidate Skill 至少通过：

1. 目标任务集：相同适用任务上的得分不能低于基线；
2. 回归任务集：非目标任务的回归必须低于阈值；
3. 成本约束：收益不能完全依赖不可接受的 Token、Latency 或 Tool Call 增长；
4. 可追溯性：必须能回到 source traces、配置和评测版本；
5. 冲突检查：与 Active Skill 冲突时必须显式解决或限定适用范围。

Promotion 原子化执行，并保留 previous_version，支持一键回退。系统不允许 Candidate 直接改写 Runtime。

## 9. Runtime、Context 与 Planning

### 9.1 最小 Runtime

第一阶段实现 Single-Agent ReAct Loop，并加入：

- `max_steps`、超时和终止原因；
- Tool Schema 校验；
- 可配置重试与错误分类；
- State Transition；
- Trace 与 Checkpoint；
- Replay。

### 9.2 Context Manager

第 t 步发送给模型的 Context：

```text
C_t = f(T, P, H_t, K_t, O_t, E_t, S_t, B)
```

其中 T 是 Task，P 是 Plan，H_t 是 History，K_t 是 Knowledge，O_t 是 Tool Observation，E_t 是 Evidence，S_t 是命中的 Skill，B 是 Token Budget。

Context Manager 在预算内选择当前决策需要的信息，不把全部历史无条件拼接。计划对比 Full History、Sliding Window、Retrieval Context 与 Retrieval + Compaction。

### 9.3 Adaptive Planning

Complexity Router 将任务分为 Simple 与 Complex：

- Simple：直接使用 ReAct；
- Complex：Plan-Execute，并允许基于新证据 Replan。

对比 ReAct、Always Planning 与 Adaptive Planning，使用 Success、Tokens、Latency 和 Steps 决定默认策略。

## 10. Trace 与可复现性

每个步骤记录：

```json
{
  "schema_version": "1.0",
  "run_id": "TBD",
  "task_id": "TBD",
  "step": 0,
  "agent": "researcher",
  "event_type": "action_selected",
  "action": "web_search",
  "arguments": {},
  "observation_ref": "TBD",
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "context_tokens": 0,
    "total_tokens": 0
  },
  "latency_ms": 0,
  "status": "TBD",
  "error_type": null,
  "config_hash": "TBD"
}
```

每次实验还要固定并记录模型、Prompt、工具版本、数据集版本、温度、随机种子（若支持）、时间戳与依赖版本。

## 11. Evaluation

### 11.1 Outcome

```text
SR = N_success / N_total
```

同时报告 Correctness、Completeness、Citation Correctness、Citation Coverage 与 Report Quality。

### 11.2 Knowledge Decision

重点报告 Knowledge Sufficiency 的 Precision、Recall 和 F1，并单列 False Negative。长期知识指标包括 Knowledge Reuse Rate、Repeated Search Reduction、Knowledge Update Accuracy、Stale Knowledge Detection 与 Conflict Detection。

### 11.3 Skill Evolution

```text
SHR = N_skill_used / N_eligible
SG = S_with_skill - S_without_skill
```

另外记录 Candidate Acceptance Rate、Promotion Rate、Regression Rate、Rollback Count、Skill Usage 与版本间增益。

### 11.4 Trajectory 与效率

- Tool Selection Accuracy；
- Tool Argument Accuracy；
- Tool Call Success Rate；
- Invalid Action Rate；
- Recovery Rate；
- Average Steps；
- Repeated Action Rate；
- Input/Output/Context Tokens；
- LLM、Wiki、Search 与 Tool Calls；
- Latency 与 Cost。

## 12. Benchmark

首版目标规模约 100 到 200 条，最终数量以标注成本和统计稳定性为准。

| 类型 | 目的 |
|---|---|
| Local-Sufficient | 检查是否产生不必要搜索 |
| Local-Partial | 评测缺口定位与定向研究 |
| Local-Missing | 评测完整外部研究 |
| Outdated | 评测时效判断与更新 |
| Conflict | 评测证据冲突处理 |
| Multi-hop | 评测 Planning |
| Long-context | 评测 Context 选择与压缩 |
| Tool-Failure | 评测错误恢复 |
| Repeated Knowledge | 评测知识复用 |
| Skill-Eligible | 评测 Skill 检索与增益 |
| Skill-Regression | 评测错误 Promotion 风险 |

部分样本必须人工标注，不能把所有结果都交给同一个 LLM Judge。

## 13. 消融矩阵

| 方案 | Success | Tokens | Search Calls | Steps | Latency | Cost |
|---|---:|---:|---:|---:|---:|---:|
| LLM + Search Baseline | TBD | TBD | TBD | TBD | TBD | TBD |
| + LLM Wiki | TBD | TBD | TBD | TBD | TBD | TBD |
| + Knowledge Sufficiency | TBD | TBD | TBD | TBD | TBD | TBD |
| + Evidence Verification | TBD | TBD | TBD | TBD | TBD | TBD |
| + Context Manager | TBD | TBD | TBD | TBD | TBD | TBD |
| + Adaptive Planning | TBD | TBD | TBD | TBD | TBD | TBD |
| + Active Skills | TBD | TBD | TBD | TBD | TBD | TBD |
| + Multi-Agent | TBD | TBD | TBD | TBD | TBD | TBD |

Skill Gate 单独报告：

| Skill 版本 | 目标任务得分 | 回归任务得分 | Skill Gain | Regression | 决策 |
|---|---:|---:|---:|---:|---|
| V1 | TBD | TBD | TBD | TBD | TBD |
| V2 | TBD | TBD | TBD | TBD | TBD |
| V3 | TBD | TBD | TBD | TBD | TBD |

## 14. 开发阶段

### Phase 0：评测先行

定义 Benchmark、Trace Schema、Eval Contract 和可复现配置。

### Phase 1：最小 ReAct 基线

完成 Runtime、State、Tool Registry、Trace 与 Replay，获得首组基线结果。

### Phase 2：长期知识接入

实现 KnowledgeProvider 与 LLMWikiProvider，对比无知识、普通 RAG 与 LLM Wiki。

### Phase 3：Knowledge-Gap-Aware Research

实现 Sufficiency、Web Research、Evidence Verification、Consolidation 与 Write Gate。

### Phase 4：Context 与 Planning

分别加入 Context Manager 和 Adaptive Planning，每一步都先消融后保留。

### Phase 5：Skill Evolution

实现 Experience Distillation、Candidate Skill、Evaluation/Regression Gate、Promotion、版本与回退。

### Phase 6：扩展实验

评估 Multi-Agent、不同模型与不同任务分布。只有收益能覆盖成本和复杂度时才进入默认架构。

## 15. 风险与约束

- Sufficiency False Negative 会导致基于残缺知识回答，需要单独监控并优先降低。
- 错误证据可能污染长期知识，所有写入必须经过来源与冲突 Gate。
- Candidate Skill 可能过拟合少量 Trace，必须使用独立目标集和回归集。
- LLM Judge 可能偏置，必须混合确定性指标、人工标注与多次复核。
- Multi-Agent 可能增加 Context、Latency 和协调失败，不预设其必然优于 Single-Agent。
- 时间敏感实验要记录运行日期；外部网页变化会影响复现。
- 任何 `XX%` 只能在真实实验后替换，并保留原始结果和配置。

## 16. 验收标准

项目达到阶段性完成，需要同时具备：

- 可运行、可终止、可恢复、可 Replay 的基线 Runtime；
- 能解释“为什么 Search”并输出缺口的 Sufficiency 决策；
- Claim 与 Evidence 可追溯的 Knowledge Evolution；
- 不能绕过 Evaluation/Regression Gate 的 Skill Promotion；
- 至少一组固定配置下的完整消融实验；
- 所有表格由真实数据生成，缺失值保留为 `TBD`；
- 文档、Trace、配置和实验结果能够相互对应。

## 17. 当前状态

| 项目 | 状态 |
|---|---|
| 需求边界 | 已确定 |
| 总体架构 | 已确定 |
| Knowledge Evolution 设计 | 已确定 |
| Skill Evolution 设计 | 已确定 |
| Benchmark | TBD |
| Runtime | TBD |
| LLM Wiki Adapter | TBD |
| 实验结果 | TBD |

下一步应先完成 Phase 0，不应跳过评测合同直接堆叠功能。
