from pathlib import Path


RUN_PS1 = Path(__file__).resolve().parents[1] / "run.ps1"


def test_windows_launcher_forwards_runtime_switches():
    content = RUN_PS1.read_text()

    assert "[switch]$Widget" in content
    assert "[switch]$Realtime" in content
    assert '"--widget"' in content
    assert '"--realtime"' in content
