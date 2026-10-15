"""仅从已有产物离线重算，不发起网络请求。"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from knowledge_gap_agent.eval.report import save_report


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="离线重算探索实验报告")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = save_report(args.input, args.output)
    print(f"离线报告已生成；观测运行：{len(report['rows'])}；仍待真人终审。")


if __name__ == "__main__":
    main()
