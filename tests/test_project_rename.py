from pathlib import Path
import subprocess


def test_tracked_project_files_contain_no_legacy_name_references():
    root = Path(__file__).resolve().parents[1]
    files = subprocess.check_output(["git", "ls-files"], cwd=root, text=True).splitlines()
    offenders = []
    for relative in files:
        path = root / relative
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if ("mcp" + "relay") in content.lower():
            offenders.append(relative)
    assert offenders == []
