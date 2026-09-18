# Knowledge-Gap-Aware Self-Evolving Agent Harness

面向知识密集型长程任务的轻量级 Agent Harness。项目关注两个问题：Agent 如何识别自己“不知道什么”，以及如何把经过验证的执行经验转化为可复用 Skill。

当前仓库处于设计与基线准备阶段。文档中的指标均为待测项；在完成可复现实验前，不声明性能提升。

## 核心闭环

### Knowledge Evolution

```text
Knowledge Retrieval
        ↓
Knowledge Sufficiency
   ├─ sufficient ──────────────→ Answer
   └─ partial / missing
              ↓
         Web Research
              ↓
      Evidence Verification
              ↓
     Knowledge Consolidation
              ↓
          LLM Wiki
              ↓
         Future Reuse
```

系统先检索本地长期知识，再判断信息是否完整、时效是否满足任务要求。只有在知识不足、过时或冲突时才触发定向 Web Research。外部证据通过来源、时效、交叉验证和冲突检查后，才允许进入长期 Knowledge Memory。

### Skill Evolution

```text
Execution Trace
      ↓
Evaluation
      ↓
Experience Distillation
      ↓
Candidate Skill
      ↓
Evaluation / Regression Gate
   ├─ pass ─→ Promotion ─→ Skill Store ─→ Future Runtime
   └─ fail ─→ Reject / Revise
```

Skill Evolution 不等于让 Agent 自动改 Prompt。系统从执行 Trace 和 Eval Feedback 中提炼候选经验，但 Candidate Skill 必须通过任务评测与回归检查后才能进入运行时。每个 Skill 保留版本、来源 Trace、适用条件、评测记录和回退信息。

## 设计边界

- Harness 自研部分：Agent Loop、结构化 State、Context Manager、Knowledge Sufficiency、Trace/Replay、Evaluation 与 Skill Gate。
- 复用基础设施：模型 API、MCP 协议、Web Search、数据库驱动与 LLM Wiki。
- LLM Wiki 作为可替换的长期知识后端，通过 `KnowledgeProvider` 接口接入，不与 Runtime 强耦合。
- 第一版建立 Single-Agent ReAct 基线。Adaptive Planning、Multi-Agent 与 Skill Promotion 都通过消融实验决定是否保留。
- 不把未验证的设计写成效果结论，不把目标指标写成实验结果。

## 计划模块

```text
runtime/       Agent Loop、State、Session、生命周期与恢复
context/       Context 选择、Token Budget 与 Compaction
planner/       复杂度路由、Plan-Execute 与 Replan
tools/         Tool Registry、执行、校验、重试与 MCP Adapter
knowledge/     检索、Sufficiency、证据验证与知识沉淀
skills/        Experience 提炼、Candidate、版本与 Promotion
tracing/       事件、Trace、Replay 与审计
eval/          Benchmark、Evaluator、回归门禁与指标
agents/        Researcher，以及后续待验证的 Reviewer/Reporter
```

## 评测方向

项目从第一天记录 Outcome、Trajectory、Tool Use、Knowledge/Skill Reuse 和 Cost，而不是只评最终答案。

| 类别 | 计划指标 | 当前值 |
|---|---|---:|
| Outcome | Task Success、Correctness、Completeness、Citation Correctness | TBD |
| Knowledge Decision | Sufficiency Precision / Recall / F1 | TBD |
| Knowledge Evolution | Knowledge Reuse Rate、Repeated Search Reduction、Update Accuracy | TBD |
| Skill Evolution | Skill Hit Rate、Skill Gain、Promotion Rate、Regression Rate | TBD |
| Trajectory | Tool Selection Accuracy、Recovery Rate、Repeated Action Rate、Steps | TBD |
| Efficiency | Tokens、Search Calls、Tool Calls、Latency、Cost | TBD |

计划中的核心消融包括：

- ReAct 与 Adaptive Planning；
- Full History、Sliding Window、Retrieval Context 与 Retrieval + Compaction；
- 无长期知识、普通 RAG 与 LLM Wiki；
- 无 Sufficiency Gate 与 Knowledge-Gap-Aware Research；
- 无 Skill、Candidate Skill 与通过 Gate 的 Active Skill；
- Single-Agent 与不同 Multi-Agent 编排。

所有实验固定模型、提示词、工具、数据集和采样参数。结果表在实验完成前统一保留为 `TBD` 或 `XX`。

## 里程碑

1. 定义 Benchmark、Trace Schema 与最小可复现配置。
2. 实现 Single-Agent ReAct Baseline，获得首组基线数据。
3. 接入 LLM Wiki，完成 Knowledge Memory 消融。
4. 实现 Knowledge Sufficiency、Web Research 和 Evidence Verification 闭环。
5. 实现 Context Manager 与 Adaptive Planning，并分别评测。
6. 从 Trace 中生成 Candidate Skill，建立 Evaluation / Regression Gate。
7. 验证 Skill Promotion、版本回退和长期收益。
8. 最后评估 Multi-Agent 与跨模型泛化；若收益不足则不进入默认架构。

完整模块设计、数据流、指标定义和实验矩阵见 [项目计划](docs/PROJECT_PLAN.md)。

## 项目状态

- 需求与总体架构：已确定
- GitHub 仓库与文档：建设中
- Runtime 实现：TBD
- Benchmark 与基线实验：TBD
- Knowledge Evolution 实验：TBD
- Skill Evolution 实验：TBD

## 许可证

TBD
