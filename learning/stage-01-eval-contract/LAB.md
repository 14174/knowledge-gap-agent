# 阶段一实验

三个实验都在本地运行，不需要外部 API key。先保留原始输出，再做修改；不要用“看起来差不多”代替字段、哈希和异常类型的对照。实验涉及的代码分别在 [demo/01_config_trace.py](../../demo/01_config_trace.py)、[demo/02_bm25_retrieval.py](../../demo/02_bm25_retrieval.py)、[src/knowledge_gap_agent/retrieval/bm25.py](../../src/knowledge_gap_agent/retrieval/bm25.py) 和 [src/knowledge_gap_agent/benchmark/models.py](../../src/knowledge_gap_agent/benchmark/models.py)。

## 统一记录模板

每个实验复制一份下面的模板。实际结果必须来自本次命令输出；如果结果与预期不同，保留差异并解释，不要改写成预期值。

```text
实验假设：
修改变量：
控制变量：
预期现象：
实际结果：
Trace 位置：
结论：
```

本阶段还没有 Runtime Trace。模板中的“Trace 位置”填写可追溯的输出字段、异常信息或测试断言，例如 `top_k[0].term_scores`、`invalid_trace_rejected`，不要虚构事件编号。

## 基础实验：运行两个 Demo

### 目的

确认配置哈希、Trace 校验、确定性分词、BM25 分项得分和主张覆盖都能从固定输入重现。

### 步骤

1. 运行配置与 Trace 演示：

   ```powershell
   uv run python demo/01_config_trace.py
   ```

2. 记录 `config_hash`、`hash_stable`、合法 Trace 中的 `usage.total_tokens`，以及 `invalid_trace_rejected`。
3. 连续运行 BM25 演示两次，并把原始字节写入临时文件：

   ```powershell
   uv run python demo/02_bm25_retrieval.py > $env:TEMP\kg-bm25-first.json
   uv run python demo/02_bm25_retrieval.py > $env:TEMP\kg-bm25-second.json
   Compare-Object (Get-Content -Raw $env:TEMP\kg-bm25-first.json) (Get-Content -Raw $env:TEMP\kg-bm25-second.json)
   Get-Content -Raw $env:TEMP\kg-bm25-first.json
   ```

4. `Compare-Object` 无输出表示两次文本相同。记录 `query_tokens`、每条结果的 `score` 与 `term_scores`、`hit_claim_ids`、`missing_claim_ids` 和三个稳定哈希。
5. 对任意一条结果手动相加 `term_scores`，核对是否等于该条 `score`（允许浮点近似误差）。

### 记录重点

- `hash_stable=True` 只证明相同配置内容不受映射键输入顺序影响；
- `missing_claim_ids` 中的主张可能存在于语料，只是对应块没有进入当前前二名；
- 不要把 Demo 输出写成正式实验结果，它只是固定小语料上的契约演示。

## 单变量参数实验：只改变 top_k

### 实验问题

固定查询为 `BM25 如何解释检索分数 人工终审 二元字组`。只把 `top_k` 从 2 改为 3，观察第三个结果能否补上 `claim-human-review`，并核对前两个共有块的 `term_scores` 是否保持不变。

### 控制要求

本实验只允许改变 `top_k`。不要同时修改查询、块正文、块顺序、`k1`、`b` 或 `REQUIRED_CLAIM_IDS`。若改了两个变量，本次实验无效。

### 步骤

下面的小脚本直接复用 Demo 的固定对象，不修改仓库文件：

```powershell
@'
import importlib

from knowledge_gap_agent.retrieval.bm25 import BM25Index

demo = importlib.import_module("demo.02_bm25_retrieval")
query = "BM25 如何解释检索分数 人工终审 二元字组"
index = BM25Index.build(demo.CHUNKS, k1=1.5, b=0.75)

def observe(top_k: int) -> dict[str, object]:
    results = index.search(query, top_k=top_k)
    returned = {item.chunk_id for item in results}
    hit_claim_ids = sorted({
        claim_id
        for chunk in demo.CHUNKS
        if chunk.chunk_id in returned
        for claim_id in chunk.claim_ids
        if claim_id in demo.REQUIRED_CLAIM_IDS
    })
    missing_claim_ids = sorted(
        set(demo.REQUIRED_CLAIM_IDS) - set(hit_claim_ids)
    )
    return {
        "top_k": top_k,
        "results": [item.to_payload() for item in results],
        "hit_claim_ids": hit_claim_ids,
        "missing_claim_ids": missing_claim_ids,
    }

for value in (2, 3):
    print(observe(value))
'@ | uv run python -
```

### 已实测观察

| 观察项 | `top_k=2` | `top_k=3` |
|---|---|---|
| 返回块编号 | `chunk-token`、`chunk-formula` | `chunk-token`、`chunk-formula`、`chunk-human-review` |
| `hit_claim_ids` | `claim-formula` | `claim-formula`、`claim-human-review` |
| `missing_claim_ids` | `claim-human-review` | 空列表 |
| 共有块的 `term_scores` | 记录 `chunk-token` 与 `chunk-formula` 的分项 | 两个共有块的分项与左列完全相同 |

实测中，`chunk-token` 的总分为 `4.399337102885296`，`chunk-formula` 的总分为 `4.045028074465003`；两组运行中这两个共有块的 `term_scores` 逐项相同。`top_k=3` 新增 `chunk-human-review`，其总分为 `3.8020193820819035`，`claim-human-review` 因此从 `missing_claim_ids` 移入 `hit_claim_ids`。这组差异来自结果截断值，不是查询或索引变化。

如果复现时共有块的分项得分发生变化，先检查是否误改了查询、语料或 BM25 参数。`top_k` 只截断排序结果，不参与建索引和单文档得分计算。

## 故障实验：制造非法环境

### 假设

同一 `chunk_id` 同时进入可见池和研究池时，环境含义不再唯一。`KnowledgeEnvironment` 应在构造阶段确定性早拒绝，不应等到检索、复核或冻结阶段。

### 步骤

运行以下脚本。它先按同一非法三池计算匹配的 `environment_hash`，排除“哈希错误”这个混杂因素；唯一故障是集合重叠。

```powershell
@'
from pydantic import ValidationError

from knowledge_gap_agent.benchmark.models import (
    KnowledgeEnvironment,
    compute_environment_hash,
)

visible = ["chunk-shared"]
research = ["chunk-shared"]
excluded = []

try:
    KnowledgeEnvironment(
        environment_id="lab-invalid-overlap",
        visible_chunk_ids=visible,
        research_chunk_ids=research,
        excluded_chunk_ids=excluded,
        environment_hash=compute_environment_hash(
            "lab-invalid-overlap", visible, research, excluded
        ),
    )
except ValidationError as exc:
    print("early_rejected=True")
    print(exc.errors()[0]["msg"])
else:
    raise AssertionError("非法环境没有被拒绝")
'@ | uv run python -
```

### 观察与解释

应观察到 `early_rejected=True`，错误信息指向三组块必须互斥。记录的 Trace 位置可写为 `KnowledgeEnvironment.validate_disjoint_sets_and_hash` 和首个校验错误。

这个故障不能通过从某一组静默删除编号来“修复”，因为程序不知道哪一组才是标注者的真实意图。正确做法是回到环境构造输入，明确该块属于可见、研究还是排除池，然后重算 `environment_hash`。

可选扩展是制造陈旧 `review_target_hash` 或向模型输入加入标签字段，但不要在同一次故障实验中同时注入多个错误，否则无法判断是哪条门禁先触发。

## 实验完成检查

- 三份记录都使用统一模板；
- 基础实验保留两个 Demo 的真实输出位置；
- 参数实验只修改 `top_k`，并对照 `term_scores` 与命中主张；
- 故障实验只制造一个非法环境，观察到确定性早拒绝；
- 没有填写正式基准指标、性能提升或人工批准结论。
