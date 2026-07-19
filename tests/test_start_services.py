from unittest.mock import Mock
from pathlib import Path
import os

import start_services


def test_venv_python_path_for_unix():
    assert start_services.venv_python_path(Path("/app"), "posix") == Path(
        "/app/.venv/bin/python"
    )


def test_venv_python_path_for_windows():
    assert start_services.venv_python_path(Path("C:/app"), "nt") == Path(
        "C:/app/.venv/Scripts/python.exe"
    )


def test_ensure_deps_falls_back_to_python_pip_without_uv(monkeypatch):
    check_call = Mock()
    sentinel = start_services.PYTHON.parent / ".deps_sentinel"
    if sentinel.exists():
        sentinel.unlink()
    monkeypatch.setattr(start_services.shutil, "which", lambda name: None)
    monkeypatch.setattr(start_services.subprocess, "check_call", check_call)

    start_services.ensure_deps()

    check_call.assert_called_once_with([
        str(start_services.PYTHON),
        "-m",
        "pip",
        "install",
        "-r",
        str(start_services.REQUIREMENTS),
    ])


def test_parse_runtime_flags_defaults_to_no_overrides():
    options = start_services.parse_args([])

    assert options.widget is False
    assert options.realtime is False

    child_env = start_services.service_environment(options)
    assert child_env["MCP_REALTIME_STATUS_ENABLED"] == "false"


def test_runtime_flags_override_child_environment_only(monkeypatch):
    monkeypatch.setenv("MCP_WIDGET_ENABLED", "false")
    monkeypatch.setenv("MCP_REALTIME_STATUS_ENABLED", "true")
    options = start_services.parse_args(["--widget"])

    child_env = start_services.service_environment(options)

    assert child_env["MCP_WIDGET_ENABLED"] == "true"
    assert child_env["MCP_REALTIME_STATUS_ENABLED"] == "true"
    assert os.environ["MCP_WIDGET_ENABLED"] == "false"
    assert os.environ["MCP_REALTIME_STATUS_ENABLED"] == "true"

def test_ensure_deps_uses_uv_for_uv_managed_venv(monkeypatch):
    import start_services
    calls = []
    sentinel = start_services.PYTHON.parent / ".deps_sentinel"
    if sentinel.exists():
        sentinel.unlink()
    monkeypatch.setattr(start_services.shutil, "which", lambda name: "/usr/local/bin/uv" if name == "uv" else None)
    monkeypatch.setattr(start_services.subprocess, "check_call", lambda command: calls.append(command))

    start_services.ensure_deps()

    assert calls == [[
        "/usr/local/bin/uv", "pip", "install", "--python", str(start_services.PYTHON),
        "-r", str(start_services.REQUIREMENTS),
    ]]
