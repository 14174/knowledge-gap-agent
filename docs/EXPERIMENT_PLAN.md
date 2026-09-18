# Experiment Plan

> 本文件用于把项目机制转化为可复现实验。当前所有结果均为 TBD。

## 1. 实验原则

每次消融只改变一个 Harness 机制，固定 Dataset、Model、Prompt Family、Tools、Sampling Config 与 Evaluator。每次 Run 保存 config hash、Trace、时间戳、模型版本和依赖版本。

## 2. Benchmark 分组

| Split | 目标 | 主要指标 |
|---|---|---|
| Local-Sufficient | 是否避免无意义 Search | Sufficiency F1, Search Calls, Success |
| Local-Partial | 是否识别具体知识缺口 | Gap Recall, Success, Search Calls |
| Local-Missing | Deep Research 能力 | Success, Citation Coverage, Cost |
| Outdated | 时效判断 | Stale Detection, Success |
| Conflict | 冲突证据处理 | Conflict Detection, Correctness |
| Multi-hop | Planning | Success, Steps, Tokens |
| Long-context | Context Engineering | Success, Context Tokens, Lost-info Rate |
| Tool-Failure | Recovery | Recovery Rate, Success |
| Repeated-Knowledge | Knowledge Evolution | Reuse Rate, Repeated Search Reduction |
| Skill-Eligible | Skill Evolution | Skill Hit Rate, Skill Gain |
| Skill-Regression | Promotion 安全性 | Regression Rate |

首版目标 100–200 条，其中核心 Sufficiency 与 Skill Gate 子集进行人工复核。

## 3. Baseline 与增量实验

### E0 Minimal Baseline

LLM + Web Search + Minimal ReAct。

输出：Task Success、Tokens、Search Calls、Steps、Latency。

### E1 Persistent Knowledge

E0 + LLM Wiki Retrieval。

验证：长期知识是否提高质量或减少 Search。

### E2 Knowledge Sufficiency

E1 + Sufficiency Gate。

验证：是否能在质量约束下减少不必要 Web Research。报告 confusion matrix、Precision、Recall、F1，并单列 false-sufficient。

### E3 Evidence Verification + Consolidation

E2 + Verification + Write Gate。

验证：写回知识是否可靠，以及第二轮 related tasks 是否真正复用。

### E4 Context Manager

比较 Full History / Sliding Window / Retrieval Context / Retrieval + Compaction。

验证：Task Success 与 Context Tokens 的 Pareto trade-off。

### E5 Planning

比较 ReAct / Always Plan / Adaptive Plan。

验证：不同复杂度任务是否存在稳定收益，以及额外 LLM Call 是否值得。

### E6 Skill Evolution

同一 held-out Skill-Eligible tasks 比较 without-skill / candidate / promoted skill。Candidate 不进入默认 Runtime。

验证：Skill Gain、Cost、Regression Rate、Rollback。

### E7 Multi-Agent

只在前述基线稳定后比较 Single Research Agent / Researcher+Reviewer / Researcher+Reviewer+Writer。

### E8 Cross-model

在至少两个能力层级不同的模型上重复关键 E2、E4、E6，验证相对增益是否依赖单一模型。

## 4. 核心结果表

| Variant | Success | Suff. F1 | Context Tokens | Search Calls | Latency | Knowledge Reuse | Skill Gain |
|---|---:|---:|---:|---:|---:|---:|---:|
| E0 | TBD | - | TBD | TBD | TBD | - | - |
| E1 | TBD | - | TBD | TBD | TBD | TBD | - |
| E2 | TBD | TBD | TBD | TBD | TBD | TBD | - |
| E3 | TBD | TBD | TBD | TBD | TBD | TBD | - |
| E4 | TBD | TBD | TBD | TBD | TBD | TBD | - |
| E5 | TBD | TBD | TBD | TBD | TBD | TBD | - |
| E6 | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

## 5. Skill Promotion Gate

每个 Candidate Skill 至少执行：

1. target eval；
2. held-out skill-eligible eval；
3. regression eval；
4. efficiency check；
5. applicability/conflict check。

Promotion 规则的具体阈值在 baseline 后确定并版本化，不能在看到 candidate 结果后临时修改阈值。

| Skill | Version | Target Δ | Held-out Δ | Cost Δ | Regression | Decision |
|---|---|---:|---:|---:|---:|---|
| TBD | V1 | TBD | TBD | TBD | TBD | TBD |

## 6. 重复知识实验

Round 1：

```text
Unknown Task → Local Miss → Research → Verification → Consolidation
```

Round 2 使用 related but non-identical task：

```text
Related Task → Knowledge Retrieval → Sufficiency → optional Research
```

比较有/无 write-back 的 Success、Search Calls、Tokens，并记录实际命中的 Knowledge ID，避免把普通模型先验误算为 Knowledge Reuse。

## 7. 失败分析

每次实验除了 aggregate metrics，还输出 failure taxonomy：

- premature search stop；
- unnecessary search；
- missing claim；
- stale evidence；
- citation mismatch；
- tool selection error；
- tool argument error；
- repeated action；
- context information loss；
- planning failure；
- bad skill retrieval；
- skill-induced regression。

Failure taxonomy 将作为 Experience Distillation 的输入，但 Eval 数据不能直接成为未经验证的 Active Skill。

## 8. 简历指标选择

实验结束后优先从以下五项选 3–4 项进入简历：

- Task Success；
- Knowledge Sufficiency F1；
- Search Calls / Repeated Search Reduction；
- Context Tokens；
- Knowledge Reuse Rate；
- Skill Gain / Regression Rate。

选择标准是能直接支撑核心机制，而不是数值看起来最大。
