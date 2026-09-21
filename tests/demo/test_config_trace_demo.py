import importlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[2]))
demo = importlib.import_module("demo.01_config_trace")
build_config = demo.build_config
build_trace_event = demo.build_trace_event
main = demo.main


def test_build_config_is_e0_and_hash_is_stable():
    config = build_config()
    assert config.variant.value == "e0"
    assert len(config.config_hash) == 64


def test_main_prints_contract_signals(capsys):
    main()
    output = capsys.readouterr().out
    assert "hash_stable=True" in output
    assert "invalid_trace_rejected=True" in output


def test_build_trace_event_has_structured_json_fields():
    payload = build_trace_event(build_config()).model_dump(mode="json")
    assert payload["agent"] == "researcher"
    assert payload["usage"]["total_tokens"] == 0
