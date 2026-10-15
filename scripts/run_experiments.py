"""真实实验显式联网入口；默认不连接服务。"""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from knowledge_gap_agent.contracts.config import RunConfig
from knowledge_gap_agent.eval.dataset import load_candidate_dataset
from knowledge_gap_agent.eval.ledger import CallLedger
from knowledge_gap_agent.eval.runner import initialize_batch, run_main, grade_phase
from knowledge_gap_agent.eval.reuse import run_reuse, freeze_reuse_questions
from knowledge_gap_agent.eval.skills import run_skill, prepare_skill_state
from knowledge_gap_agent.eval.io import write_once
from knowledge_gap_agent.runtime.model import MessagesClient


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="候选数据探索实验，联网必须显式指定--live")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--phase", choices=("smoke", "prepare", "main", "grade", "reuse", "skill", "all"), default="smoke")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=os.environ.get("ANTHROPIC_MODEL"))
    parser.add_argument("--model-revision", default="service-reported")
    parser.add_argument("--budget", type=int, default=2400)
    parser.add_argument("--max-steps", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--retry-limit", type=int, default=1)
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("此命令会请求真实模型；请显式添加--live。离线重算使用report_experiments.py。")
    if args.repeats < 1:
        parser.error("重复次数必须大于零")
    if not args.model:
        parser.error("请指定--model或设置ANTHROPIC_MODEL，不猜测服务模型身份。")
    dataset = load_candidate_dataset(ROOT)
    config = RunConfig(experiment_id="candidate-sprint-v1", variant="e0", model_provider="compatible-messages-proxy",
             model_name=args.model, model_revision=args.model_revision, temperature=0,
             max_steps=args.max_steps, timeout_seconds=args.timeout, retry_limit=args.retry_limit,
             prompt_hash="0" * 64, toolset_version="frozen-corpus-bm25-v1", dataset_version=dataset.dataset_hash,
             corpus_hash=dataset.source_hashes["fixtures/corpus/chunks.jsonl"], random_seed=20261015)
    initialize_batch(dataset, args.output, config, repeats=args.repeats, budget=args.budget)
    freeze_reuse_questions(dataset, args.output)
    ledger = CallLedger(args.output / "calls.sqlite", limit=args.budget)
    def factory(run_config):
        return MessagesClient.from_env(run_config, before_attempt=lambda: ledger.reserve(run_config.variant.value))
    # 先确认鉴权存在，再调度任务；凭据不进入日志或配置。
    factory(config)
    if args.phase in ("smoke", "all"):
        run_main(dataset, config, args.output, factory, repeats=1, workers=args.workers, development=True)
    if args.phase in ("prepare", "main", "grade", "reuse", "skill", "all"):
        prepare_skill_state(dataset, config, args.output, factory, repeats=args.repeats)
    if args.phase in ("main", "all"):
        run_main(dataset, config, args.output, factory, repeats=args.repeats, workers=args.workers)
    if args.phase in ("grade", "all"):
        grade_phase(dataset, config, args.output, factory, phase="main", workers=args.workers)
    if args.phase in ("reuse", "all"):
        run_reuse(dataset, config, args.output, factory, repeats=args.repeats, workers=args.workers)
    if args.phase in ("skill", "all"):
        try:
            gate = run_skill(dataset, config, args.output, factory, repeats=args.repeats, workers=args.workers)
            write_once(args.output / "skill/gate.json", gate)
        except Exception as exc:
            # 没有有效候选是实验结果，不能偷偷创建固定策略假装提炼成功。
            write_once(args.output / "skill/execution_error.json", {"status": "候选未完成", "reason": type(exc).__name__})
    print(f"实验产物已保存，实际预留请求：{ledger.used}/{ledger.limit}；数据仍待真人终审。")


if __name__ == "__main__":
    main()
