#!/usr/bin/env python3
"""
Starts the unified MCP gateway on port 8761.

The gateway serves both:
  - MCP endpoint at  http://localhost:8761/mcp
  - OAuth endpoints  http://localhost:8761/oauth/*  (mounted internally)

Usage (single terminal):
    python3 start_services.py

Then tunnel with ngrok:
    ngrok http 8761
"""

import os
import argparse
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"


def venv_python_path(base_dir: Path, platform_name: str = os.name) -> Path:
    if platform_name == "nt":
        return base_dir / ".venv" / "Scripts" / "python.exe"
    return base_dir / ".venv" / "bin" / "python"


PYTHON = venv_python_path(BASE_DIR)
REQUIREMENTS = BASE_DIR / "requirements.txt"
LOG_DIR = Path(os.environ.get("MCP_LOG_ROOT", BASE_DIR / "logs")) / "services"
LOG_DIR.mkdir(parents=True, exist_ok=True)
GATEWAY_HOST = "0.0.0.0"
GATEWAY_PORT = 8761

SERVICES = [
    {
        "name": "gateway",
        "cmd": [str(PYTHON), str(SRC_DIR / "mcp_gateway.py")],
        "log": LOG_DIR / "gateway.log",
    },
]

processes = []


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Start the Gate gateway")
    parser.add_argument("--widget", action="store_true", help="enable the ChatGPT command widget")
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="enable queued commands and realtime status tools",
    )
    return parser.parse_args(argv)


def service_environment(options) -> dict[str, str]:
    env = os.environ.copy()
    env["MCP_REALTIME_STATUS_ENABLED"] = "true" if options.realtime or options.widget else "false"
    if options.widget:
        env["MCP_WIDGET_ENABLED"] = "true"
    return env


def is_port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def ensure_venv():
    if not PYTHON.exists():
        print(".venv missing, creating it...")
        subprocess.check_call([sys.executable, "-m", "venv", str(BASE_DIR / ".venv")])


def ensure_deps():
    subprocess.check_call([
        str(PYTHON),
        "-m",
        "pip",
        "install",
        "-r",
        str(REQUIREMENTS),
    ])


def start_service(service, env=None):
    log_file = open(service["log"], "a", buffering=1, encoding="utf-8")
    log_file.write(f"\n--- starting {service['name']} at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")

    process = subprocess.Popen(
        service["cmd"],
        cwd=str(BASE_DIR),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=env or os.environ.copy(),
    )

    processes.append((service, process, log_file))
    print(f"started {service['name']} pid={process.pid} log={service['log']}")


def stop_all(*_):
    print("stopping services...")

    for service, process, log_file in processes:
        if process.poll() is None:
            print(f"stopping {service['name']} pid={process.pid}")
            process.terminate()

    time.sleep(2)

    for service, process, log_file in processes:
        if process.poll() is None:
            print(f"killing {service['name']} pid={process.pid}")
            process.kill()
        log_file.close()

    sys.exit(0)


def main(argv=None):
    options = parse_args(argv)
    child_env = service_environment(options)
    ensure_venv()
    ensure_deps()

    if not is_port_available(GATEWAY_HOST, GATEWAY_PORT):
        print(f"gateway port {GATEWAY_PORT} is already in use; stop the existing gateway before starting a new one")
        sys.exit(1)

    signal.signal(signal.SIGINT, stop_all)
    signal.signal(signal.SIGTERM, stop_all)

    for service in SERVICES:
        start_service(service, child_env)
        time.sleep(1)

    print("services running")
    print(f"gateway log: {LOG_DIR / 'gateway.log'}")
    print()
    print("  MCP    → http://localhost:8761/mcp")
    print("  OAuth  → http://localhost:8761/oauth/...")
    print("  Health → http://localhost:8761/oauth/health")
    print()
    print("press Ctrl+C to stop")

    while True:
        for service, process, log_file in list(processes):
            code = process.poll()
            if code is not None:
                print(f"{service['name']} exited with code {code}; restarting...")
                processes.remove((service, process, log_file))
                log_file.close()
                start_service(service, child_env)
        time.sleep(3)


if __name__ == "__main__":
    main()
