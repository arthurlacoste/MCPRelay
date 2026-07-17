from pathlib import Path


def test_installer_is_pipe_safe_and_does_not_require_git():
    content = (Path(__file__).resolve().parents[1] / "install.sh").read_text()

    assert "/dev/tty" in content
    assert "api.github.com/repos/arthurlacoste/gate/releases/latest" in content
    assert "git clone" not in content
    assert '"$HOME/.local/bin/gate"' in content
    assert "~/.gate/current" in content or '"$GATE_ROOT/current"' in content


def test_installer_bootstraps_uv_nvm_node_and_ngrok():
    content = (Path(__file__).resolve().parents[1] / "install.sh").read_text()

    assert "uv" in content
    assert "nvm" in content
    assert 'NODE_VERSION="22"' in content
    assert "ngrok" in content
    assert "Start Gate now? [Y/n]" in content

def test_installer_does_not_depend_on_system_python():
    content = (Path(__file__).resolve().parents[1] / "install.sh").read_text()
    assert "| python3 -c" not in content
    assert 'uv run --python "$PYTHON_VERSION" python -c' in content

def test_installer_requires_release_checksum_asset():
    content = (Path(__file__).resolve().parents[1] / "install.sh").read_text()
    assert "SHA256SUMS" in content
    assert "verify_archive_checksum" in content

def test_installer_downloads_github_release_assets():
    content = (Path(__file__).resolve().parents[1] / "install.sh").read_text()
    assert "/releases/latest" in content
    assert "browser_download_url" in content
    assert "SHA256SUMS" in content
    assert "checksums.txt" not in content

def test_generated_launcher_exposes_src_package():
    content = (Path(__file__).resolve().parents[1] / "install.sh").read_text()
    assert 'export PYTHONPATH="$ROOT/current/src${PYTHONPATH:+:$PYTHONPATH}"' in content
    assert '"$ROOT/current/.venv/bin/python" -m gate_cli' in content
