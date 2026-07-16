import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "count_conversation_tools.py"


def test_counts_top_level_tools_across_jsonl_files(tmp_path):
    (tmp_path / "first.jsonl").write_text(
        '{"tool":"alpha","type":"mcp_call"}\n'
        '{"tool":"beta","type":"mcp_call"}\n'
        '{"arguments":{"tool":"nested"},"type":"note"}\n'
    )
    (tmp_path / "second.jsonl").write_text(
        '{"tool":"alpha","type":"mcp_call"}\n'
        'not-json\n'
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "COUNT\tTOOL",
        "2\talpha",
        "1\tbeta",
        "",
        "total_calls\t3",
        "unique_tools\t2",
        "files_scanned\t2",
        "invalid_lines\t1",
    ]
