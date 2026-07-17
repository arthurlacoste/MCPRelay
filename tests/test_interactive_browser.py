from pathlib import Path


def test_interactive_launcher_contains_no_browser_opening_code():
    source = (Path(__file__).resolve().parents[1] / "src" / "interactive_launcher.py").read_text()
    assert "webbrowser" not in source
    assert "open_chatgpt_setup" not in source
    assert "open_url(" not in source
