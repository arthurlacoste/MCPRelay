from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path


DCG_VERSION = "v0.6.7"
DCG_REPOSITORY = "https://github.com/Dicklesworthstone/destructive_command_guard"
TARGETS = {
    ("Linux", "x86_64"): ("x86_64-unknown-linux-musl", "tar.xz"),
    ("Linux", "aarch64"): ("aarch64-unknown-linux-gnu", "tar.xz"),
    ("Darwin", "x86_64"): ("x86_64-apple-darwin", "tar.xz"),
    ("Darwin", "arm64"): ("aarch64-apple-darwin", "tar.xz"),
    ("Windows", "AMD64"): ("x86_64-pc-windows-msvc", "zip"),
    ("Windows", "ARM64"): ("aarch64-pc-windows-msvc", "zip"),
}


def release_asset() -> tuple[str, str]:
    key = (platform.system(), platform.machine())
    if key not in TARGETS:
        raise RuntimeError(f"dcg is unsupported on {key[0]} {key[1]}")
    target, extension = TARGETS[key]
    return f"dcg-{target}.{extension}", extension


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Gate command guard installer"})
    with urllib.request.urlopen(request, timeout=30) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


def verify_checksum(asset: Path, checksum_file: Path) -> None:
    expected = checksum_file.read_text(encoding="utf-8").split()[0].lower()
    actual = hashlib.sha256(asset.read_bytes()).hexdigest()
    if len(expected) != 64 or actual != expected:
        raise RuntimeError("dcg SHA256 verification failed")


def verify_executable(executable: Path) -> str:
    completed = subprocess.run([str(executable), "--version"], capture_output=True, text=True, timeout=5, check=False, shell=False)
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode or DCG_VERSION.removeprefix("v") not in output:
        raise RuntimeError("dcg executable version verification failed")
    return output.splitlines()[0]


def install(destination: Path) -> str:
    asset_name, extension = release_asset()
    base = f"{DCG_REPOSITORY}/releases/download/{DCG_VERSION}"
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gate-dcg-") as temporary:
        root = Path(temporary)
        asset = root / asset_name
        checksum = root / f"{asset_name}.sha256"
        _download(f"{base}/{asset_name}", asset)
        _download(f"{base}/{asset_name}.sha256", checksum)
        verify_checksum(asset, checksum)
        extract = root / "extract"
        extract.mkdir()
        if extension == "zip":
            with zipfile.ZipFile(asset) as archive:
                archive.extractall(extract)
        else:
            with tarfile.open(asset, "r:xz") as archive:
                archive.extractall(extract, filter="data")
        name = "dcg.exe" if platform.system() == "Windows" else "dcg"
        candidates = list(extract.rglob(name))
        if len(candidates) != 1:
            raise RuntimeError("dcg release archive did not contain one executable")
        target = destination / name
        shutil.copy2(candidates[0], target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
    return verify_executable(target)


def _set_env(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    keys = set(values)
    kept = [line for line in lines if not any(line.startswith(f"{key}=") for key in keys)]
    kept.extend(f"{key}={value}" for key, value in values.items())
    temporary = path.with_suffix(".tmp")
    temporary.write_text("\n".join(kept) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def configure(config_root: Path, bin_dir: Path, provider: str, non_interactive: bool = False) -> dict[str, str]:
    selected = provider.lower()
    if selected not in {"builtin", "dcg"}:
        raise ValueError("provider must be builtin or dcg")
    values = {"MCP_COMMAND_GUARD_PROVIDER": selected, "MCP_COMMAND_GUARD_FALLBACK": "builtin"}
    if selected == "dcg":
        executable = shutil.which("dcg")
        try:
            version = verify_executable(Path(executable)) if executable else install(bin_dir)
            executable = executable or str(bin_dir / ("dcg.exe" if platform.system() == "Windows" else "dcg"))
            values.update({"MCP_DCG_EXECUTABLE": executable, "MCP_DCG_VERSION": version})
        except Exception as exc:
            print(f"dcg setup failed ({type(exc).__name__}); using builtin guard.")
            values["MCP_COMMAND_GUARD_PROVIDER"] = "builtin"
    _set_env(config_root / ".env", values)
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-root", type=Path, required=True)
    parser.add_argument("--bin-dir", type=Path, required=True)
    parser.add_argument("--provider", choices=("builtin", "dcg"), default="builtin")
    args = parser.parse_args()
    print(json.dumps(configure(args.config_root, args.bin_dir, args.provider)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
