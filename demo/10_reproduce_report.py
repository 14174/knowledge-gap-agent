"""输入实际目录时离线重算；缺省仅展示样例模式。"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from knowledge_gap_agent.eval.report import build_report, markdown_report


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    args = parser.parse_args(argv)
    if args.input:
        print(markdown_report(build_report(args.input)))
    else:
        print("样例模式：没有提供真实实验产物，不输出任务成功率或性能提升。")
        print("输入：固定协议与真实运行目录 → 中间：保留失败、按主题配对 → 输出：离线统计报告。")
        print("请用--input指定包含protocol.json与runs的实际目录。")


if __name__ == "__main__":
    main()
