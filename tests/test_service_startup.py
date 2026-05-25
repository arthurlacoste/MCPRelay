from pathlib import Path
import socket

import start_services


def test_is_port_available_reports_free_and_bound_ports():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        host, port = sock.getsockname()

        assert start_services.is_port_available(host, port) is False

    assert start_services.is_port_available(host, port) is True


def test_run_sh_reads_colon_separated_pid_file():
    script = Path('run.sh').read_text(encoding='utf-8')

    assert script.count('IFS=: read -r SERVICES_PID NGROK_PID < "$PID_FILE"') == 2
