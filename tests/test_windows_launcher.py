from pathlib import Path


RUN_PS1 = Path(__file__).resolve().parents[1] / "run.ps1"


def test_windows_launcher_forwards_runtime_switches():
    content = RUN_PS1.read_text()

    assert "[switch]$Widget" in content
    assert "[switch]$Queue" in content
    assert "[switch]$Realtime" in content
    assert "[switch]$ConnectTs" in content
    assert '"--widget"' in content
    assert '"--queue"' in content
    assert '-m gate_cli connect ts' in content


def test_windows_launcher_creates_skills_directory():
    content = RUN_PS1.read_text()

    assert '$env:MCP_SKILLS_ROOT' in content
    assert 'Join-Path $HOME ".gate\\skills"' in content
    assert 'New-Item -ItemType Directory -Path $SkillsRoot -Force' in content
