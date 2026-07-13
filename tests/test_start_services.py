from unittest.mock import Mock
from pathlib import Path

import start_services


def test_venv_python_path_for_unix():
    assert start_services.venv_python_path(Path("/app"), "posix") == Path(
        "/app/.venv/bin/python"
    )


def test_venv_python_path_for_windows():
    assert start_services.venv_python_path(Path("C:/app"), "nt") == Path(
        "C:/app/.venv/Scripts/python.exe"
    )


def test_ensure_deps_installs_requirements_file(monkeypatch):
    check_call = Mock()
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
