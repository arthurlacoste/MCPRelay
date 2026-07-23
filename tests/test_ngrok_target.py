from subprocess import CompletedProcess

from src import ngrok_target


def test_override_wins_on_every_platform():
    assert ngrok_target.resolve_ngrok_target(
        8761,
        {"GATE_NGROK_TARGET": "gateway.internal:8761"},
        "linux",
    ) == "gateway.internal:8761"


def test_non_macos_uses_local_port():
    assert ngrok_target.resolve_ngrok_target(8761, {}, "linux") == "8761"


def test_macos_uses_first_lan_address(monkeypatch):
    responses = iter(("", "172.20.10.2\n"))
    monkeypatch.setattr(
        ngrok_target.subprocess,
        "run",
        lambda *args, **kwargs: CompletedProcess(args[0], 0, next(responses), ""),
    )

    assert ngrok_target.resolve_ngrok_target(8761, {}, "darwin") == "172.20.10.2:8761"


def test_macos_falls_back_to_local_port(monkeypatch):
    monkeypatch.setattr(
        ngrok_target.subprocess,
        "run",
        lambda *args, **kwargs: CompletedProcess(args[0], 1, "", ""),
    )

    assert ngrok_target.resolve_ngrok_target(8761, {}, "darwin") == "8761"
