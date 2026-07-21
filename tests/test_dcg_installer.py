import hashlib
from pathlib import Path

import pytest

import dcg_installer


def test_release_assets_cover_supported_platforms(monkeypatch):
    monkeypatch.setattr(dcg_installer.platform, "system", lambda: "Linux")
    monkeypatch.setattr(dcg_installer.platform, "machine", lambda: "x86_64")
    assert dcg_installer.release_asset() == ("dcg-x86_64-unknown-linux-musl.tar.xz", "tar.xz")


def test_unsupported_platform_is_clear(monkeypatch):
    monkeypatch.setattr(dcg_installer.platform, "system", lambda: "Plan9")
    monkeypatch.setattr(dcg_installer.platform, "machine", lambda: "mips")
    with pytest.raises(RuntimeError, match="unsupported"):
        dcg_installer.release_asset()


def test_checksum_is_mandatory(tmp_path):
    asset = tmp_path / "dcg"
    checksum = tmp_path / "dcg.sha256"
    asset.write_bytes(b"verified")
    checksum.write_text(hashlib.sha256(b"verified").hexdigest() + "  dcg\n")
    dcg_installer.verify_checksum(asset, checksum)
    checksum.write_text("0" * 64)
    with pytest.raises(RuntimeError, match="SHA256"):
        dcg_installer.verify_checksum(asset, checksum)


def test_configuration_defaults_builtin_and_preserves_existing_env(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / ".env").write_text("KEEP=value\n")
    values = dcg_installer.configure(config, tmp_path / "bin", "builtin")
    text = (config / ".env").read_text()
    assert values["MCP_COMMAND_GUARD_PROVIDER"] == "builtin"
    assert "KEEP=value" in text
    assert "MCP_COMMAND_GUARD_FALLBACK=builtin" in text


def test_dcg_failure_persists_builtin_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(dcg_installer.shutil, "which", lambda _: None)
    monkeypatch.setattr(dcg_installer, "install", lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
    values = dcg_installer.configure(tmp_path / "config", tmp_path / "bin", "dcg")
    assert values["MCP_COMMAND_GUARD_PROVIDER"] == "builtin"
