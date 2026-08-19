from pathlib import Path

from environment_config import gateway_paths, load_gateway_environment, mcp_servers_config_path


def test_gateway_paths_use_external_roots_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_CONFIG_ROOT", str(tmp_path / "config"))
    monkeypatch.setenv("MCP_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("MCP_LOG_ROOT", str(tmp_path / "logs"))

    paths = gateway_paths(tmp_path / "release")

    assert paths.config == tmp_path / "config"
    assert paths.data == tmp_path / "data"
    assert paths.logs == tmp_path / "logs"


def test_mcp_servers_config_path_maps_config_prefix_to_persistent_root(tmp_path, monkeypatch):
    config_root = tmp_path / "persistent-config"
    monkeypatch.setenv("MCP_CONFIG_ROOT", str(config_root))
    monkeypatch.setenv("MCP_SERVERS_CONFIG", "config/mcp.json")

    assert mcp_servers_config_path(tmp_path / "release") == config_root / "mcp.json"


def test_mcp_servers_config_path_preserves_absolute_override(tmp_path, monkeypatch):
    absolute = tmp_path / "custom" / "servers.json"
    monkeypatch.setenv("MCP_CONFIG_ROOT", str(tmp_path / "persistent-config"))
    monkeypatch.setenv("MCP_SERVERS_CONFIG", str(absolute))

    assert mcp_servers_config_path(tmp_path / "release") == absolute


def test_gateway_environment_loads_external_env(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / ".env").write_text("GATE_EXTERNAL_ENV=yes\n")
    monkeypatch.setenv("MCP_CONFIG_ROOT", str(config))
    monkeypatch.delenv("GATE_EXTERNAL_ENV", raising=False)

    assert load_gateway_environment(tmp_path / "release")
    assert __import__("os").environ["GATE_EXTERNAL_ENV"] == "yes"


def test_gateway_environment_disables_background_catalog_refresh_by_default(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / ".env").write_text("GATE_EXTERNAL_ENV=yes\n")
    monkeypatch.setenv("MCP_CONFIG_ROOT", str(config))
    monkeypatch.delenv("MCP_DISCOVERY_REFRESH_INTERVAL_SECONDS", raising=False)

    load_gateway_environment(tmp_path / "release")

    assert __import__("os").environ["MCP_DISCOVERY_REFRESH_INTERVAL_SECONDS"] == "0"


def test_gateway_environment_preserves_explicit_catalog_refresh_interval(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / ".env").write_text("MCP_DISCOVERY_REFRESH_INTERVAL_SECONDS=15\n")
    monkeypatch.setenv("MCP_CONFIG_ROOT", str(config))
    monkeypatch.delenv("MCP_DISCOVERY_REFRESH_INTERVAL_SECONDS", raising=False)

    load_gateway_environment(tmp_path / "release")

    assert __import__("os").environ["MCP_DISCOVERY_REFRESH_INTERVAL_SECONDS"] == "15"


def test_gateway_and_oauth_modules_use_gateway_paths_helper():
    root = Path(__file__).resolve().parents[1]
    gateway = (root / "src" / "mcp_gateway.py").read_text()
    oauth = (root / "src" / "lightweight_oauth.py").read_text()

    assert "gateway_paths(BASE_DIR)" in gateway
    assert "gateway_paths(BASE_DIR)" in oauth
    assert "BASE_DIR / 'logs'" not in gateway
    assert 'BASE_DIR / "data"' not in oauth


def test_gateway_registry_uses_persistent_config_root_across_versioned_release(tmp_path):
    import json
    import os
    import shutil
    import subprocess
    import sys

    release = tmp_path / "releases" / "v0.1.36"
    release.mkdir(parents=True)
    source_root = Path(__file__).resolve().parents[1] / "src"
    release_source = release / "src"
    shutil.copytree(
        source_root,
        release_source,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    config_root = tmp_path / "config"
    config_root.mkdir()
    (config_root / ".env").write_text(
        "MCP_SERVERS_CONFIG=config/mcp.json\n",
        encoding="utf-8",
    )
    (config_root / "mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(release_source)
    env["MCP_CONFIG_ROOT"] = str(config_root)
    env["MCP_DATA_ROOT"] = str(tmp_path / "data")
    env["MCP_LOG_ROOT"] = str(tmp_path / "logs")
    env["ENABLE_OAUTH"] = "false"
    env["MCP_COMMAND_QUEUE_ENABLED"] = "false"
    env.pop("MCP_SERVERS_CONFIG", None)

    script = """
import asyncio
import json
import mcp_gateway

async def main():
    await mcp_gateway.proxy_manager.refresh()
    print(json.dumps({
        "base_dir": str(mcp_gateway.BASE_DIR),
        "config_path": str(mcp_gateway.proxy_manager.registry.config_path),
        "error": mcp_gateway.proxy_manager.registry._last_refresh_error,
    }))

asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=release,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload == {
        "base_dir": str(release),
        "config_path": str(config_root / "mcp.json"),
        "error": None,
    }
