import importlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[2]))
demo = importlib.import_module("demo.01_config_trace")
build_config = demo.build_config
main = demo.main


def test_build_config_is_e0_and_hash_is_stable():
    config = build_config()
    assert config.variant.value == "e0"
    assert len(config.config_hash) == 64


def test_main_prints_contract_signals(capsys):
    main()
    output = capsys.readouterr().out
    assert "hash_stable=True" in output
    assert '"agent": "researcher"' in output
    assert '"total_tokens": 0' in output
    assert "invalid_trace_rejected=True" in output
