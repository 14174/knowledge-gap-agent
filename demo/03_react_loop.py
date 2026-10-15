"""固定响应演示：研究后作答与非法动作终止。"""
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demo.fixed_runtime import FixedModel, build_config, research, success_model
from knowledge_gap_agent.runtime.loop import run_task
from knowledge_gap_agent.runtime.models import TaskInput


def main() -> None:
    print("固定响应演示；不联网，不代表真实模型效果。")
    config = build_config()
    task = TaskInput(question="冻结模型的集合如何保存？")
    result = run_task(task, config, success_model(config), research)
    print(f"成功路径={result.stop_reason}；回答={result.answer}；事件数={len(result.events)}")
    failed = run_task(task, config, FixedModel(config, ("非法动作",)), research)
    print(f"失败路径={failed.stop_reason}")


if __name__ == "__main__":
    main()
