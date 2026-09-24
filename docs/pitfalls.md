# 工程陷阱

## 破坏性测试污染版本化夹具

### 复现条件

测试直接向仓库内 `fixtures/` 写入 sentinel、非法 JSON 或追加日志，再依靠 `finally` 恢复原字节。测试与其他读取任务并行时，读取者会在恢复前看到中间状态。

### 影响

单条测试最终恢复成功，仍可能让并行测试、审查进程或开发者读取损坏夹具。失败栈和重试结果因此不稳定，也无法证明版本化数据从未被改写。

### 根因

构建脚本把仓库根目录作为隐式全局读写位置。测试没有可注入的工作区根目录，只能修改真实夹具来覆盖错误分支。

### 回归测试

`tests/benchmark/test_fixture_dataset.py` 的 `test_rebuild_uses_explicit_isolated_workspace` 验证 `--workspace-root` 指向隔离副本。自动夹具 `real_fixtures_remain_unchanged` 在每条测试前后比较真实夹具树哈希。

### 禁止做法

不得在测试中写入、删除或追加版本化 `fixtures/`。破坏性场景必须先复制到 `tmp_path/workspace`，所有构建命令都显式传入 `--workspace-root`。

## case 状态绕过正式人工门禁

### 复现条件

调用方通过 `model_copy(update={"human_review_status": "approved"})` 修改高风险 case，再调用只检查状态字段的正式冻结接口。调用方不需要提供审核者、理由、时间或绑定内容版本的人工记录。

### 影响

模型结论或程序写入的状态可以伪装成人工批准。正式数据无法回答“谁在什么时间审核了哪个版本”，高风险样本会在没有真实人工终审的情况下发布。

### 根因

旧实现把 `human_review_status` 同时当作缓存和授权凭据。Pydantic 的 `model_copy()` 不重新验证，冻结器也没有要求独立、不可变且绑定当前目标哈希的人工记录。

### 回归测试

`tests/benchmark/test_freeze.py` 的 `test_forged_case_approval_cannot_replace_human_record` 固定状态伪造攻击；`test_formal_freeze_requires_exact_human_review_case_set` 和 `test_formal_freeze_rejects_stale_human_review_target_without_writes` 固定集合与目标版本边界。

### 禁止做法

不得把 `human_review_status`、模型 `approve` 或清单中的空字段当成人工批准。正式冻结只接受集合精确、绑定当前 `review_target_hash` 且结论为 `approved` 的 `HumanReviewRecord`。
