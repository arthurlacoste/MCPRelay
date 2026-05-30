import plistlib
import subprocess
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def test_gateway_launchagent_runs_run_sh_start():
    plist_path = BASE_DIR / "config" / "com.mymcp.gateway.plist"

    with open(plist_path, "rb") as f:
        payload = plistlib.load(f)

    assert payload["Label"] == "com.mymcp.gateway"
    assert payload["RunAtLoad"] is True
    assert payload["WorkingDirectory"] == str(BASE_DIR)
    assert payload["ProgramArguments"] == [
        "/bin/bash",
        "-lc",
        f"cd {BASE_DIR} && ./run.sh start",
    ]


def test_setup_startup_dry_run():
    script = BASE_DIR / "setup-startup.sh"

    subprocess.run(["bash", "-n", str(script)], check=True)
    result = subprocess.run(
        [str(script), "--dry-run"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Would install:" in result.stdout
    assert "com.mymcp.gateway.plist" in result.stdout
