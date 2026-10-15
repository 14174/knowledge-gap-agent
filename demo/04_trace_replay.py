"""固定响应完整轨迹保存与离线重放。"""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demo.fixed_runtime import build_config, research, success_model
from knowledge_gap_agent.runtime.loop import run_task
from knowledge_gap_agent.runtime.models import TaskInput
from knowledge_gap_agent.tracing.store import replay_run, save_run


def main() -> None:
    print("固定响应演示；重放不调用网络或研究工具。")
    config = build_config()
    result = run_task(TaskInput(question="冻结集合用什么？"), config, success_model(config), research)
    with TemporaryDirectory(prefix="knowledge-gap-demo-") as directory:
        path = save_run(result, directory)
        replayed = replay_run(path)
        print(f"重放一致={replayed == result}；调用数={len(replayed.calls)}")


if __name__ == "__main__":
    main()
