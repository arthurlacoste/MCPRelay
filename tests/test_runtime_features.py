import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from runtime_features import RuntimeFeatures, runtime_mode_summary


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_features_library_default_keeps_queue_without_widget():
    features = RuntimeFeatures.from_environ({})

    assert features.command_queue_enabled is True
    assert features.widget_enabled is False


def test_widget_enables_queue_when_not_explicitly_enabled(caplog):
    with caplog.at_level(logging.INFO):
        features = RuntimeFeatures.from_environ({
            "MCP_WIDGET_ENABLED": "true",
            "MCP_COMMAND_QUEUE_ENABLED": "false",
        })

    assert features.command_queue_enabled is True
    assert features.widget_enabled is True
    assert "widget enables the asynchronous command queue" in caplog.text.lower()


def test_legacy_realtime_environment_variable_remains_supported():
    features = RuntimeFeatures.from_environ({"MCP_REALTIME_STATUS_ENABLED": "false"})

    assert features.command_queue_enabled is False


def test_runtime_modes_are_documented():
    env_example = (ROOT / "config" / ".env.example").read_text()
    installation = (ROOT / "docs" / "installation.md").read_text()

    assert "MCP_WIDGET_ENABLED=false" in env_example
    assert "MCP_COMMAND_QUEUE_ENABLED=false" in env_example
    assert "--widget" in installation
    assert "--queue" in installation
    assert "run.ps1 -Queue" in installation
    assert "run.ps1 -Widget" in installation


def test_runtime_mode_summary_reports_effective_choices():
    features = RuntimeFeatures(command_queue_enabled=True, widget_enabled=False)

    assert runtime_mode_summary(features) == "queue=on monitor=on widget=off"
