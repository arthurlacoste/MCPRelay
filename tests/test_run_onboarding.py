from pathlib import Path


RUN_SCRIPT = Path(__file__).resolve().parents[1] / "run.sh"


def test_run_script_onboards_before_starting_services():
    content = RUN_SCRIPT.read_text()

    interactive = content.index("run_interactive()")
    daemon = content.index("start_daemon()")

    assert content.index("ensure_onboarding", interactive) < content.index(
        "python3 start_services.py", interactive
    )
    assert content.index("ensure_onboarding", daemon) < content.index(
        "nohup python3 start_services.py", daemon
    )


def test_onboarding_persists_url_secret_and_hash():
    content = RUN_SCRIPT.read_text()

    assert 'OAUTH_ACCESS_SECRET "$access_secret"' in content
    assert 'OAUTH_ACCESS_SECRET_HASH "$access_hash"' in content
    assert 'MCP_BASE_URL "$public_url"' in content
    assert 'chmod 600 "$CONFIG_FILE"' in content


def test_onboarding_reuses_complete_configuration():
    content = RUN_SCRIPT.read_text()

    assert '[ -n "$public_url" ] && [ -n "$access_secret" ]' in content
    assert '[[ "$access_hash" == \\$argon2id\\$* ]]' in content
