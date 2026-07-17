from pathlib import Path

from environment_config import gateway_paths, load_gateway_environment


def test_gateway_paths_use_external_roots_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_CONFIG_ROOT", str(tmp_path / "config"))
    monkeypatch.setenv("MCP_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("MCP_LOG_ROOT", str(tmp_path / "logs"))

    paths = gateway_paths(tmp_path / "release")

    assert paths.config == tmp_path / "config"
    assert paths.data == tmp_path / "data"
    assert paths.logs == tmp_path / "logs"


def test_gateway_environment_loads_external_env(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / ".env").write_text("GATE_EXTERNAL_ENV=yes\n")
    monkeypatch.setenv("MCP_CONFIG_ROOT", str(config))
    monkeypatch.delenv("GATE_EXTERNAL_ENV", raising=False)

    assert load_gateway_environment(tmp_path / "release")
    assert __import__("os").environ["GATE_EXTERNAL_ENV"] == "yes"

def test_gateway_and_oauth_modules_use_gateway_paths_helper():
    root = Path(__file__).resolve().parents[1]
    gateway = (root / "src" / "mcp_gateway.py").read_text()
    oauth = (root / "src" / "lightweight_oauth.py").read_text()

    assert "gateway_paths(BASE_DIR)" in gateway
    assert "gateway_paths(BASE_DIR)" in oauth
    assert "BASE_DIR / 'logs'" not in gateway
    assert 'BASE_DIR / "data"' not in oauth
