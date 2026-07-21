from pathlib import Path

import pytest

from gate_cli.changelog import version_notes
from gate_cli.migrations import MigrationError, run_migrations
from gate_cli.paths import GatePaths
from gate_cli.release_flow import update_with_lifecycle


def test_version_notes_extracts_only_requested_release(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## 0.2.0\n\n- New CLI\n\n## 0.1.0\n\n- Initial\n")
    assert version_notes(changelog, "0.2.0") == "- New CLI"


def test_update_running_gate_prompts_stops_and_restarts(tmp_path):
    events = []

    result = update_with_lifecycle(
        is_running=lambda: True,
        confirm=lambda prompt: events.append(prompt) or True,
        stop=lambda: events.append("stop") or 0,
        update=lambda: events.append("update") or ("0.2.0", True),
        start=lambda: events.append("start") or 0,
    )

    assert result == ("0.2.0", True)
    assert events == ["Gate is running. Stop it and continue? [Y/n] ", "update", "stop", "start"]



def test_update_failure_keeps_running_gate_online():
    events = []

    with pytest.raises(RuntimeError, match="rate limit"):
        update_with_lifecycle(
            is_running=lambda: True,
            confirm=lambda prompt: events.append("confirm") or True,
            stop=lambda: events.append("stop") or 0,
            update=lambda: events.append("update") or (_ for _ in ()).throw(RuntimeError("rate limit exceeded")),
            start=lambda: events.append("start") or 0,
        )

    assert events == ["confirm", "update"]

def test_update_running_gate_can_be_cancelled():
    called = []
    result = update_with_lifecycle(
        is_running=lambda: True,
        confirm=lambda prompt: False,
        stop=lambda: called.append("stop") or 0,
        update=lambda: called.append("update") or ("0.2.0", True),
        start=lambda: called.append("start") or 0,
    )
    assert result is None
    assert called == []


def test_migration_failure_restores_backup_and_writes_safe_report(tmp_path):
    paths = GatePaths.from_home(tmp_path)
    paths.ensure_persistent()
    env = paths.config / ".env"
    env.write_text("OAUTH_ACCESS_SECRET=do-not-leak\nVALUE=before\n")

    def migration(_context):
        env.write_text("OAUTH_ACCESS_SECRET=do-not-leak\nVALUE=broken\n")
        raise RuntimeError("boom")

    with pytest.raises(MigrationError) as caught:
        run_migrations(paths, "0.1.0", "0.2.0", [migration])

    assert "VALUE=before" in env.read_text()
    report = caught.value.report
    content = report.read_text()
    assert "boom" in content
    assert "do-not-leak" not in content
    assert "github.com/spelcc/gate/issues/new" in caught.value.issue_url
