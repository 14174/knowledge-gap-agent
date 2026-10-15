# 知识缺口驱动的智能体执行框架

面向固定知识任务的轻量级研究原型：判断本地证据是否够用，必要时研究，验证后写回，并用隔离评测检验机制。实现使用 Python、Pydantic、SQLite 和确定性 BM25，不依赖智能体框架。

运行时、轨迹重放、知识闭环、候选技能门禁及隔离评测均已实现；384次主运行、48次复用运行、96次候选运行与评分已完成。主批次2085次请求尝试，全部归档。二十四条高风险候选仍待真人终审，不冒充正式数据冻结或生产效果。

实测 E2 成功83/96，充分性F1为0.873；但相对有知识对照没有减少搜索，质量差区间跨零；写回未证明缺失知识复用，退化技能被拒绝。详见[总报告](docs/首轮实验总报告.md)、[最终交付清单](docs/最终交付清单.md)和[简历证据卡](docs/简历证据卡.md)，不把负结果包装成成本收益。

## 从哪里开始

- 学习：[五阶段课程](learning/README.md)，每阶段指南、实验、八道练习及评分点答案。
- 开发：[协作规则](AGENTS.md)、[工程规范](docs/AI_CODING_GUIDE.md)、[架构](docs/architecture.md)、[模块索引](docs/module_index.md)。
- 执行：[连续交付索引](docs/superpowers/plans/2026-10-15-全项目交付索引.md)、[实验设计](docs/superpowers/specs/2026-10-15-真实实验与统计设计.md)、[中间报告](docs/reports/)。
- 数据：[基准构造依据与过程](docs/benchmark-construction.md)、[真人终审清单](docs/阶段一人工终审清单.md)。

## 安装与离线演示

```powershell
uv sync --extra dev
$env:PYTHONUTF8='1'
uv run python -m pytest -q
uv run python demo/01_config_trace.py
uv run python demo/02_bm25_retrieval.py
uv run python demo/03_react_loop.py
uv run python demo/04_trace_replay.py
uv run python demo/05_knowledge_provider.py
uv run python demo/06_sufficiency_gate.py
uv run python demo/07_evidence_gate.py
uv run python demo/08_round_trip_reuse.py
uv run python demo/09_candidate_skill_gate.py
uv run python demo/10_reproduce_report.py
```

十个演示默认离线；固定响应和配对只验证工程行为，不产生真实效果指标。第十个演示未提供真实目录时只展示使用说明。全量验收记录见实验报告，不把测试数量当模型能力。

## 闭环与职责

```text
问题与可见证据 → 充分性判断 → 足够：限定作答
                          → 不足：研究 → 回答 → 提取 → 独立验证 → SQLite写回
后续不同问题 → 检索新增知识 → 判断与作答 → 检查是否实际引用

开发轨迹 → 冻结候选与目标/回归分集 → 同题配对评测 → 离线通过或拒绝
完成的运行 → 独立读取评分标签 → 按主题配对统计 → 离线重算报告
```

运行模型不接收答案、类别、必需主张或缺口标签。研究工具仅检索固定环境的可见池与研究池，排除池不可访问。模型请求是真实远端请求，研究材料是固定语料，不声称开放网页搜索。

写回必须通过结构检查与单独模型语义验证，保存正文、完整来源关系及凭据。技能即使通过仍不自动进入默认策略。离线重放重新执行状态机，不重新请求模型，也不等于远端再次生成可重复。

## 真实实验与复现

仅显式联网命令请求现有兼容消息服务。预先配置环境变量 `ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN`；不要把密钥写入仓库。

```powershell
uv run python scripts/run_experiments.py --live --phase all --model deepseek-v4-flash --model-revision provider-reported-unpinned --repeats 3 --workers 4 --budget 2400 --output artifacts/experiments/my-new-batch
uv run python scripts/report_experiments.py --input artifacts/experiments/my-new-batch --output artifacts/reports/my-report
uv run python demo/10_reproduce_report.py --input artifacts/experiments/my-new-batch
```

同目录恢复只允许相同配置、代码与数据摘要；重新设计使用新批次。每次 HTTP 尝试提前计入持久预算，失败不退还，未知用量不按零计算。服务模型别名不能保证固定权重；记录实际返回模型，不编造可验证版本或金额。

当前协议使用十二主题、每题四环境共四十八条候选；开发主题01–04，留出主题05–12。每变体三次，共三百八十四次主运行；复用和技能另行配对。重复调用不是独立主题扩容，区间按八个主题成簇计算。失败保留主分母，缺评分单列，裁判成本与运行成本分开。

## 实现边界

本轮完成最小动作循环、错误终止、完整轨迹与重放、SQLite/BM25、充分性、验证写回、候选门禁、真实对照及课程。未实现逐步检查点恢复、上下文压缩、自适应规划、多智能体编排、特定知识产品适配、自动晋升或回退；未验证跨模型、开放网页和生产泛化。

[长期项目计划](docs/PROJECT_PLAN.md)、[长期实验路线](docs/EXPERIMENT_PLAN.md)和[原面试问题库](docs/RESUME_AND_INTERVIEW.md)保留历史设想，不能当作当前功能清单。当前分支 `codex/full-project-delivery` 供最终审阅；正式冻结与课程标签等待真实人工审核。

## 许可证

尚未选择项目许可证；外部教程来源与固定提交见来源清单，不推定其内容授权可由本仓库重新授予。
