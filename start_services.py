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
import signal
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
PYTHON = BASE_DIR / ".venv" / "bin" / "python"
LOG_DIR = BASE_DIR / "logs" / "services"
LOG_DIR.mkdir(exist_ok=True)

# ── Single gateway: serves both MCP (port 8761 /mcp) and OAuth ──
SERVICES = [
    {
        "name": "gateway",
        "cmd": [str(PYTHON), str(SRC_DIR / "mcp_gateway.py")],
        "log": LOG_DIR / "gateway.log",
    },
]

processes = []


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
        "fastmcp",
        "python-dotenv",
        "fastapi",
        "uvicorn",
        "pyjwt",
        "cryptography",
        "python-multipart",
        "pyautogui",
        "pillow",
    ])


def start_service(service):
    log_file = open(service["log"], "a", buffering=1, encoding="utf-8")
    log_file.write(f"\n--- starting {service['name']} at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")

    process = subprocess.Popen(
        service["cmd"],
        cwd=str(BASE_DIR),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=os.environ.copy(),
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


def main():
    ensure_venv()
    ensure_deps()

    signal.signal(signal.SIGINT, stop_all)
    signal.signal(signal.SIGTERM, stop_all)

    for service in SERVICES:
        start_service(service)
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
                start_service(service)
        time.sleep(3)


if __name__ == "__main__":
    main()
