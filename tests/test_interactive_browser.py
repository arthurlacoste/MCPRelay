from pathlib import Path

import interactive_launcher


def test_open_chatgpt_after_health_check(monkeypatch):
    events = []
    monkeypatch.setattr(interactive_launcher, "wait_for_oauth_health", lambda: events.append("health") or True)
    monkeypatch.setattr(interactive_launcher, "open_url", lambda url: events.append(url) or True)

    assert interactive_launcher.open_chatgpt_setup()
    assert events == ["health", interactive_launcher.CHATGPT_CONNECTOR_URL]
