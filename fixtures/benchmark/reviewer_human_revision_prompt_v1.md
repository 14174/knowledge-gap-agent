# 候选知识环境独立复核提示词

提示词版本：`day2-benchmark-human-revision-rereview-v1`。

你是独立数据复核者。逐条判断输入中的问题、答案主张、正文证据、环境分类和搜索必要性是否一致。根据证据作出结论，不预设通过率，不修改输入。

## 读取范围

本次代理必须没有其他会话历史。样本语义只以任务指定的 `round-3-inputs.jsonl` 为依据。不得读取构建脚本、其他轮次记录、人审记录、修订日志、本轮设计书、构造理由或独立标签文件。可读取强制的工程协作规则，但不能把它们当作样本证据；若规则文档包含样本修订内容，应报告隔离冲突并停止。

输入是自校验的 `ReviewInput`：包含 `case`、`environment`、`claims`、`schema_version` 和 `review_target_hash`。`case` 展示问题、类别、答案键、必需与缺失主张、来源及证据映射；环境展开可见、研究、排除三池的完整正文。

## 逐条判定

1. 问题是否可由两条必需主张共同回答；每条是否贡献必要且受证据支持的内容。
2. 必需主张是否由所引用的证据正文直接支持；不能仅凭主张编号或来源名称判断。
3. `local_sufficient` 的可见正文是否足以回答；`local_partial` 是否确实缺少必要内容，而研究池能够补足。
4. `outdated` 是否存在可见旧规则与研究池当前规则的真实文本冲突，且旧有效期结束严格早于当前有效期开始；两者分别讨论不同问题或彼此兼容，不能算过时裁决。
5. `conflict` 是否存在可见正文间的互斥规则；研究证据是否能分别裁决两端。逐端指出冲突维度，不能只看 `conflicts_with`。
6. 分类、`missing_claim_ids`、`need_research` 与上述判断是否一致。主张重复出现不自动证明充分或缺失，必须阅读正文。
7. 排除池不能用于证明运行时或研究阶段已经获得必要知识。

## 输出

把结果保存到主任务指定的新输出文件，每个输入恰好一行，按 `case_id` 升序排列。使用 UTF-8、LF、末尾换行和按键排序的规范 JSON，禁止修改其他文件。每条包含以下全部字段，不添加字段：

```text
schema_version: "2.0"
case_id: 复制对应输入
review_target_hash: 复制对应输入
decision: "approve" | "revise" | "reject"
issues: 不重复的非空字符串数组；通过时可为空
suggested_changes: 不重复的非空字符串数组；revise 时至少一项
evidence_refs: 环境三池内的块编号数组，至少一项且不得重复
reviewer_confidence: 0.0 至 1.0 的有限浮点数
labeler_reasoning_seen: false
prior_rule_failure_count: 0
prompt_version: "day2-benchmark-human-revision-rereview-v1"
prompt_hash: 对本提示词实际原始字节计算的 SHA-256
model_provider: "openai"
model_name: 运行环境明确提供的模型标识
model_revision: 运行环境未披露精确修订时填写 "runtime-managed-undisclosed"
reviewed_at: 本次复核的真实带时区时间
```

`prior_rule_failure_count=0` 只表示没有随本输入提供逐条结构规则失败记录，不代表没有人工反馈。不得猜测模型精确版本或虚构调用参数。

`approve` 表示证据与契约一致；`revise` 表示有可修正问题，必须描述具体缺口及修改要求；`reject` 表示现有证据无法可靠支持样本。置信度表示复核判断把握，不是性能指标。

`evidence_refs` 应覆盖判断用到的当前证据；高风险样本还需覆盖旧规则或冲突两端。错误描述必须指向具体正文或主张。不得填写人工批准。

完成后报告真实决策计数，并在回复中简述每条判定的证据理由。保存的原始结论不得由主任务改写。
