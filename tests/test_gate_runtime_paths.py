from pathlib import Path


def test_run_script_uses_external_config_and_log_roots():
    root = Path(__file__).resolve().parents[1]
    content = (root / "run.sh").read_text()
    assert 'CONFIG_ROOT="${MCP_CONFIG_ROOT:-$PROJECT_DIR/config}"' in content
    assert 'NGROK_LOG="${MCP_LOG_ROOT:-$PROJECT_DIR/logs}/ngrok.log"' in content


def test_start_services_uses_external_log_root():
    root = Path(__file__).resolve().parents[1]
    content = (root / "start_services.py").read_text()
    assert 'MCP_LOG_ROOT' in content
