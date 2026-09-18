# 简历与面试准备

> 本文用于反向约束项目实现：只有代码、Trace 和可复现实验能够支持的内容，才能进入最终简历。所有尚未测得的数字统一使用 `TBD`，禁止把目标值写成结果。

## 1. 项目定位

**项目名称：Knowledge-Gap-Aware Self-Evolving Agent Harness**

一句话介绍：

> 面向知识密集型长程任务，自研轻量级 Agent Harness，通过 Knowledge Sufficiency 判断动态决策本地知识复用与 Web Research，并将验证后的外部知识沉淀至长期 Knowledge Memory；进一步从历史执行 Trace 与 Eval Feedback 中提炼 Candidate Skill，经 Evaluation/Regression Gate 验证后进入 Runtime，实现知识与执行经验的持续演化。

项目与普通“LangGraph + RAG + MCP”项目的区别：

- 研究对象是 Harness 的决策机制，而不是单一聊天应用。
- 明确判断“什么时候应该搜索”，而不是固定 RAG→Search 流程。
- Knowledge Memory 与 Procedural/Skill Memory 分离。
- 自进化不是自动改 Prompt，而是 Experience → Candidate → Evaluation → Promotion。
- 每个主要机制都要求有 baseline、ablation、Trace 和成本指标。

## 2. 简历版本

### 2.1 当前设计阶段可写版本

在 Runtime 与实验尚未完成前，不建议把项目写成“已实现”。如果必须放在简历，可标注为个人在研项目：

**Knowledge-Gap-Aware Self-Evolving Agent Harness｜个人项目（在研）**

- 设计面向知识密集型任务的 Agent Harness，拆分 Runtime、Context、Tool/MCP、Persistent Knowledge、Tracing 与 Evaluation 模块，以自研 ReAct Runtime 为基线并通过统一 Trace 支持 Replay 与消融实验。
- 设计 Knowledge Sufficiency 机制，在本地知识检索后判断 Enough / Partial / Missing，根据知识缺口动态触发定向 Web Research，并规划 Evidence Verification、Conflict Detection 与 Knowledge Consolidation 闭环。
- 参考 Hermes 的 procedural memory 思路，将 Knowledge Memory 与 Skill Memory 分离；设计 Trace → Evaluation → Experience Distillation → Candidate Skill → Evaluation/Regression Gate 的 Skill Evolution 流程，避免未经验证的经验直接修改 Runtime。
- 设计覆盖 Outcome、Trajectory、Tool Use、Efficiency、Knowledge Reuse 与 Skill Gain 的 Agent Benchmark，计划固定 Model/Prompt/Tools 对 Memory、Context、Planning 与 Multi-Agent 策略进行消融。

### 2.2 第一阶段实现完成后的目标版本

以下只有对应功能真正完成后才使用：

**Knowledge-Gap-Aware Self-Evolving Agent Harness｜个人项目**

- 自研 ReAct Agent Runtime 与结构化 State，完成 Tool Registry、Schema Validation、Timeout/Retry、Trace/Replay 等机制；构建 Agent Benchmark，从 Outcome、Trajectory、Tool Use 与 Cost 多维度评估执行质量。
- 接入 LLM Wiki 作为可替换 Persistent Knowledge Backend，设计 Knowledge Sufficiency 判断，根据本地知识完整度与时效动态触发 Web Research；经 Evidence Verification 后沉淀长期知识，使重复任务 Search Calls 从 `TBD` 降至 `TBD`，Knowledge Reuse Rate 达 `TBD`。
- 设计动态 Context Manager，根据 Task State 选择 History、Knowledge、Tool Observation、Evidence 与 Skill，并进行 Token-budget Compaction；在 Task Success `TBD` 的条件下将平均 Context Tokens 从 `TBD` 降至 `TBD`。
- 基于历史 Trace 与 Eval Feedback 提炼 Candidate Skills，通过目标任务 Evaluation 与 Regression Gate 后进行版本化 Promotion；在 held-out Skill-Eligible Benchmark 上 Skill Gain 为 `TBD`，Regression Rate 为 `TBD`。

### 2.3 最终简历数字的最低要求

最终至少给出三类真实数字：

1. **质量**：Task Success / Correctness / Sufficiency F1 至少一个；
2. **效率**：Tokens / Search Calls / Latency / Cost 至少一个；
3. **长期演化**：Knowledge Reuse / Repeated Search Reduction / Skill Gain 至少一个。

不要堆五六个百分比。优先选择能直接证明核心卖点的 3–4 个指标。

## 3. 面试开场

### Q1：用一分钟介绍一下这个项目。

**简答：**

这个项目是一个面向知识密集型任务的自研 Agent Harness。核心解决两个问题：第一，Agent 怎么判断本地知识够不够，而不是每次都盲目搜索；第二，Agent 怎么从历史任务中积累经过验证的执行经验。我先搭最小 ReAct Runtime 和 Trace/Eval 基线，再加入 Knowledge Sufficiency，缺知识时才做 Web Research，验证后写入 LLM Wiki；另一条链路从历史 Trace 提炼 Candidate Skill，但必须经过离线 Evaluation 和 Regression Gate 才能进入后续 Runtime。整个项目通过固定模型、Prompt 和 Tools 做消融，评估 Success、Tokens、Search Calls、Knowledge Reuse 和 Skill Gain。

**展开重点：**

面试官继续问时再展开 Runtime、Knowledge Loop、Skill Loop 和 Evaluation，不要一上来把所有模块全部讲完。

---

## 4. Runtime / Harness

### Q2：Agent、Workflow 和 Harness 有什么区别？

**简答：**

Workflow 的控制流主要由开发者预定义；Agent 会根据当前 State 和 Observation 动态决定下一步 Action；Harness 是承载 Agent 的运行基础设施，包括 Loop、State、Context、Tool Execution、Tracing、Recovery、Memory 接口和 Evaluation。LLM 只是 Harness 中负责决策或生成的一部分。

**展开：**

本项目的 Research Agent 是 workload，Harness 才是研究主体。相同 Research Task 可以在不同 Runtime/Context/Planning 策略下执行，从而做公平消融。

### Q3：为什么自己写 Runtime，不直接使用 LangGraph？

**简答：**

不是为了重复造轮子，而是因为 Runtime 行为本身就是项目要研究的变量。如果 Agent Loop、State Transition、Context 和 Recovery 全交给框架，我很难控制变量分析具体机制。模型 API、MCP、数据库等标准基础设施仍然直接复用。

**追问链：**

- 那你自己实现了哪些部分？
- 哪些部分坚决不自己实现？
- 如果生产环境为什么可能重新使用 LangGraph？
- 如何证明自研 Runtime 没有为了“自研”而增加无意义复杂度？

### Q4：ReAct Loop 怎么终止，怎么避免死循环？

**简答：**

同时使用语义终止和系统终止。模型可以输出 Final Answer；Runtime 还设置 max_steps、timeout、重复 Action 检测、连续 Tool Failure 阈值和不可恢复错误终止。所有终止原因写入 Trace。

**展开：**

Repeated Action 不能只比较字符串，要对 Tool name + normalized arguments + observation/result 做组合判断，否则相同 Tool 的合理迭代搜索会被误杀。

### Q5：State、Session、Memory 为什么要分开？

**简答：**

State 是单任务当前执行状态；Session 是多个任务或多轮交互的容器；Memory 是跨 Session 的长期信息。Memory 又分 Knowledge Memory 和 Procedural/Skill Memory。生命周期和检索方式不同，所以不能混在 messages 里。

---

## 5. Knowledge Gap

### Q6：Knowledge Sufficiency 到底怎么判断？

**简答：**

先检索本地知识，再让 Sufficiency Evaluator 对“当前任务需要哪些 Claim”和“已有证据覆盖哪些 Claim”做结构化判断，输出 Enough / Partial / Missing、missing evidence、stale/conflict 和 confidence。第一版用 LLM structured output，后续对 Rule、LLM Judge 和小分类器做比较。

**展开：**

Sufficiency 不是简单的 retrieval score。向量相似度只能说明“检索结果和 Query 像不像”，不能说明证据是否完整、是否过期、能否支持最终结论。

### Q7：Knowledge Sufficiency 怎么构造 Ground Truth？

**简答：**

Benchmark 在生成 Task 时同时标注 required claims、local KB coverage 和是否需要外部证据。部分样本人工复核。这样可以把 Agent 的 Enough/Partial/Missing 与标注比较，计算 Precision、Recall、F1，而不是让另一个 LLM 自己给自己打分。

### Q8：Sufficiency 的哪种错误更危险？

**简答：**

把“不充分”误判成“充分”通常更危险，因为系统会停止搜索并基于残缺知识直接回答。项目会单列这种错误，并根据任务风险和时效要求调整 decision threshold。

**追问链：**

- Precision/Recall 具体哪个对应这种错误？
- 为什么不直接把 threshold 调得非常保守？
- 保守搜索会增加多少 Cost？
- 不同任务是否应该使用不同阈值？

### Q9：为什么不是每次都 Web Search？

**简答：**

搜索有 Token、Latency 和 API Cost，而且可能引入噪声。对重复任务尤其浪费。Sufficiency Gate 的目标是在质量约束下减少不必要 Research，而不是单纯追求 Search Calls 越少越好。

### Q10：时间敏感知识怎么办？

**简答：**

Knowledge Entry 保存来源、更新时间和适用时效。Sufficiency 不只判断语义覆盖，还判断 freshness。对明显时间敏感任务可以加入 policy：即使本地内容完整，也要求外部 verification。

---

## 6. Knowledge Evolution

### Q11：搜索结果为什么不能直接写入 LLM Wiki？

**简答：**

搜索结果只是 Evidence，不等于可复用 Knowledge。直接写入会把网页噪声、重复内容、冲突信息和过时信息污染长期记忆，所以先做 Evidence Verification、Claim-Evidence 对齐、去重、冲突检测和 Consolidation，再进入 Write Gate。

### Q12：LLM Wiki 和普通 Vector DB 有什么区别？

**简答：**

在 Harness 层我不绑定具体后端，两者都实现 KnowledgeProvider。LLM Wiki 提供更完整的 ingest、Wiki、向量检索和知识组织能力，所以第一版直接复用；普通 Vector DB 会作为更简单的 baseline。是否需要知识图谱最终也必须通过检索和任务实验验证。

### Q13：怎么证明 Knowledge Evolution 有用？

**简答：**

设计 repeated/related task benchmark。第一次任务允许 Research 并写入知识，第二次相关任务比较有无长期知识时的 Task Success、Search Calls、Tokens 和 Knowledge Reuse Rate。这样测的是“知识是否真的被后续任务复用”，而不是只统计知识库条目数量。

---

## 7. Hermes 与 Skill Evolution

### Q14：你的 Self-Evolution 和 Hermes 有什么关系？

**简答：**

我借鉴的是 Hermes 把事实型 Memory 和 procedural Skill 分开的思想，但项目没有直接复制 Hermes Runtime。我的重点是增加可量化的 Evaluation/Regression Gate：历史经验首先形成 Candidate Skill，只有在独立任务集上证明收益且没有明显回归后才 Promotion。

### Q15：为什么“知识库越来越大”不能直接叫 Self-Evolution？

**简答：**

知识增长只改变 Agent “知道什么”，不一定改变“怎么做”。我把 Evolution 分为 Knowledge Evolution 和 Skill Evolution。后者从执行 Trace 中学习可复用的 procedure，才会直接改变未来 Planning、Search 或 Tool Use 行为。

### Q16：什么经验值得生成 Skill？

**简答：**

不是每次 Reflection 都生成。优先从重复失败模式、稳定成功路径、有效 Recovery 和明确用户纠正中聚类/提炼，并要求有 source trace。一次偶然成功通常只能成为 Candidate Evidence，不能直接 Promotion。

### Q17：怎么防止 Agent 学到错误 Skill？

**简答：**

Candidate 与 Active 完全隔离。Candidate 先跑目标任务集验证增益，再跑 Regression Set 检查副作用，同时记录 Token/Latency Cost。只有满足 gate threshold 才原子化 Promotion，并保留 previous version 支持 rollback。

### Q18：Skill Gain 怎么测？

**简答：**

对同一组 Skill-Eligible held-out tasks，在其他配置一致时分别运行 with-skill 和 without-skill，定义 Skill Gain 为两组任务得分差异。同时必须看成本和回归集，不能只报告目标任务提高。

### Q19：为什么不让 Agent 自动修改 System Prompt？

**简答：**

System Prompt 是全局行为策略，一次局部经验修改它容易造成不可预测回归。Skill 有明确 applicability、版本和来源，更容易做局部加载、A/B Evaluation 和 rollback，所以第一阶段选择 Skill Evolution 而不是 unrestricted self-modification。

---

## 8. Context Engineering

### Q20：Context 太长怎么处理？

**简答：**

Context Manager 在 Token Budget 内，从 Task、Plan、Recent History、Knowledge、Observation、Evidence 和 Skills 中选择当前决策需要的信息；旧历史进行 compaction，而不是简单把全部 messages 发送给模型。

### Q21：怎么证明 Compaction 没丢关键信息？

**简答：**

对比 Full History、Sliding Window、Retrieval Context 和 Retrieval+Compaction，在 Long-context Benchmark 上同时测 Success 和 Context Tokens，并专门记录 Lost-information Failure。目标不是 Token 最少，而是质量-成本 Pareto 改善。

---

## 9. Planning

### Q22：为什么不所有任务都 Plan-Execute？

**简答：**

Planning 本身也消耗一次或多次模型调用，而且简单任务的计划很快失效或只是复述问题。因此先用 ReAct baseline，再比较 Always Planning 和 Adaptive Planning，让 Complexity Router 只对确实受益的任务启用 Planning。

### Q23：ReAct 和 Plan-Execute 最大区别是什么？

**简答：**

ReAct 更强调根据每一步 Observation 即时决定下一步，适合动态环境；Plan-Execute 先形成结构化子目标，再逐步执行，长程任务全局性更强但计划维护成本更高。实际 Harness 可以混合：先 Plan，再在每个 step 内 ReAct，并允许 Replan。

---

## 10. Tools / MCP

### Q24：Tool Description 为什么重要？

**简答：**

模型通常通过 tool name、description 和 schema 判断何时调用以及怎么传参。描述边界模糊会导致 Tool Selection 错误；Schema 不严格则会增加 Argument Error。因此 Tool Evaluation 要把 Selection Accuracy 和 Argument Accuracy 分开。

### Q25：MCP 和 Function Calling 有什么区别？

**简答：**

Function Calling 主要解决模型如何结构化表达“我要调用哪个函数以及参数是什么”；MCP 更关注 Agent/Host 如何以标准协议发现和连接外部 Tool、Resource、Prompt 等能力。一个偏模型调用接口，一个偏外部能力互操作协议，两者可以同时存在。

### Q26：Tool 失败怎么办？

**简答：**

Executor 把 timeout、validation error、transient failure、permission error、not-found 等错误归一化。只有可恢复错误按 policy retry；否则 Observation 返回 Agent 让其选择替代 Tool、修改参数或终止。不能所有异常都无脑重试。

---

## 11. Multi-Agent

### Q27：为什么项目第一版不用 Multi-Agent？

**简答：**

Multi-Agent 会增加 Token、Latency、状态同步和协调失败。如果 Single Agent 都没有稳定 baseline，就无法判断提升来自角色分工还是单纯更多推理预算。因此它放在最后作为消融项。

### Q28：什么情况下 Multi-Agent 可能有效？

**简答：**

当任务天然存在可分离角色、需要并行独立证据或 Reviewer 能发现 Researcher 的系统性错误时更有价值。例如 Researcher/Reviewer。但是否值得保留最终看质量增益能否覆盖协调成本。

---

## 12. Evaluation

### Q29：为什么不能只看最终答案？

**简答：**

两个 Agent 都可能答对，但一个用了 3 次 Tool，另一个循环了 20 步后碰巧答对；也可能最终答案错是因为检索、Tool 参数、Sufficiency 或 synthesis 中不同环节导致。Trajectory Eval 能定位错误来源并指导 Harness 改进。

### Q30：LLM-as-a-Judge 靠谱吗？

**简答：**

可以用于开放式 Completeness/Report Quality，但不能成为唯一 Ground Truth。确定性任务优先程序判断；Sufficiency、Tool Selection 等建立人工/结构化标签；LLM Judge 固定模型和 Prompt，并保留 reason，必要时多 Judge 或人工抽检。

### Q31：怎么保证 Ablation 公平？

**简答：**

一次只改变一个机制，固定 dataset、model、prompt family、tools、sampling config 和 evaluation；随机任务多次运行并报告方差。所有 run 保存 config hash 和 Trace，避免“不同版本 Prompt 比不同架构”的伪消融。

### Q32：换模型后还有效吗？

**简答：**

这正是 Cross-model Evaluation 要回答的问题。如果机制只对一个模型有效，就不能把收益归因于通用 Harness。核心 ablation 会在多个能力层级模型上重复，比较绝对结果和相对增益。

---

## 13. 高频连续追问链

### 13.1 Knowledge Gap 深挖

```text
Sufficiency 怎么判断？
→ Ground Truth 从哪来？
→ retrieval score 为什么不够？
→ False Sufficient 有什么后果？
→ Precision / Recall 怎么取舍？
→ threshold 如何设？
→ 时间敏感任务怎么办？
→ Rule / LLM / Classifier 为什么这样选？
→ 搜索成本怎么计入？
→ 怎么证明减少 Search 没牺牲质量？
```

### 13.2 Self-Evolution 深挖

```text
什么叫 Self-Evolution？
→ 和普通 Memory 有什么区别？
→ Experience 怎么从 Trace 提炼？
→ 什么情况下生成 Candidate Skill？
→ 怎么避免错误经验污染？
→ Evaluation Set 怎么构造？
→ Regression Gate 检查什么？
→ Skill applicability 怎么定义？
→ 多个 Skill 冲突怎么办？
→ 版本如何回滚？
→ 怎么证明 V2 比 V1 真正更好？
```

### 13.3 Harness 深挖

```text
为什么不用 LangGraph？
→ Agent Loop 自己怎么写？
→ State Transition 怎么定义？
→ Tool timeout 怎么恢复？
→ Context 怎么控制？
→ Planning 什么时候开启？
→ Trace 如何 Replay？
→ 如何保证实验可复现？
→ 哪些基础设施应该复用？
→ 如果上线生产，你会重构哪些部分？
```

## 14. 实验结束后如何更新简历

每次准备替换 `TBD` 时检查：

- 数字是否来自固定 Benchmark，而不是挑选案例；
- baseline 是否明确；
- 是否保存 run/config/trace；
- 是否能解释为什么提高；
- 是否同时检查质量与成本；
- Skill 指标是否来自 held-out task；
- 是否存在 Regression；
- 面试时能否在白板上解释指标计算。

最终简历的目标不是“模块最多”，而是能形成一条完整证据链：

```text
Problem
→ Hypothesis
→ Mechanism
→ Controlled Experiment
→ Metric
→ Result
→ Failure Analysis
→ Design Decision
```

这也是本项目最重要的面试价值。
