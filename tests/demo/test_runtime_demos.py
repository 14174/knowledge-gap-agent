import importlib
from pathlib import Path
import subprocess

import pytest


def test_fixed_runtime_demo(capsys):
    importlib.import_module("demo.03_react_loop").main()
    output = capsys.readouterr().out
    assert "固定响应" in output
    assert "answered" in output and "invalid_action" in output


def test_fixed_replay_demo(capsys):
    importlib.import_module("demo.04_trace_replay").main()
    assert "重放一致=True" in capsys.readouterr().out


@pytest.mark.parametrize("script", ["03_react_loop.py", "04_trace_replay.py"])
def test_direct_script_command(script):
    result = subprocess.run(["uv", "run", "python", f"demo/{script}"],
        cwd=Path(__file__).parents[2], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
