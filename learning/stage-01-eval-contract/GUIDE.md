# 阶段一：评测契约

本阶段只关注已经实现的可验证边界：`RunConfig` 通过 `model_dump(mode="json")` 只生成 JSON 兼容数据，再由 `sha256_hex` 内部调用 `canonical_json` 完成键排序、紧凑序列化和非有限值拒绝，最后计算稳定 SHA-256；字段顺序变化不影响哈希，改变随机种子会改变哈希。

规范 JSON 通过 `model_dump(mode="json")` 产生。`TraceEvent` 记录运行、任务、步骤、agent、事件类型、参数、观测引用、令牌用量、延迟、状态与配置哈希；失败必须带 `error_type`，成功不得带它。`BenchmarkCase` 用六类标签表达本地知识状态，并约束是否需要研究。

代码导航：`src/knowledge_gap_agent/contracts/config.py`、`trace.py`、`benchmark.py`、`src/knowledge_gap_agent/utils/canonical.py`；演示入口为 `demo/01_config_trace.py`，测试在 `tests/contracts/` 与 `tests/demo/`。

成功观察是 `hash_stable=True`、合法 Trace JSON 中存在 `agent` 与 `usage.total_tokens`；失败观察是缺少 `error_type` 的失败事件被 `ValidationError` 拒绝。
