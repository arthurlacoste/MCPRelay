import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace


def load_start_services():
    path = Path('start_services.py').resolve()
    spec = importlib.util.spec_from_file_location('start_services_under_test', path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_ssl_preflight_checks_venv_interpreter(monkeypatch):
    module = load_start_services()
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, 'run', fake_run)
    module.ensure_ssl()

    assert calls == [
        (
            [str(module.PYTHON), '-c', 'import _ssl'],
            {
                'capture_output': True,
                'text': True,
                'check': False,
            },
        )
    ]


def test_ssl_preflight_exits_when_venv_python_has_no_ssl(monkeypatch, capsys):
    module = load_start_services()
    monkeypatch.setattr(
        module.subprocess,
        'run',
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )

    try:
        module.ensure_ssl()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError('ensure_ssl() should stop startup')

    assert 'without SSL support' in capsys.readouterr().err
