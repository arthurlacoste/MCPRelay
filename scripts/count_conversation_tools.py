#!/usr/bin/env python3
"""Count top-level MCP tool events in conversation JSONL logs."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


DEFAULT_LOG_DIR = Path(__file__).resolve().parents[1] / "logs" / "conversations"


def count_tools(log_dir: Path) -> tuple[Counter[str], int, int]:
    counts: Counter[str] = Counter()
    files = sorted(log_dir.rglob("*.jsonl"))
    invalid_lines = 0

    for path in files:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    invalid_lines += 1
                    continue

                tool = record.get("tool") if isinstance(record, dict) else None
                if isinstance(tool, str) and tool.strip():
                    counts[tool.strip()] += 1

    return counts, len(files), invalid_lines


def print_report(counts: Counter[str], files_scanned: int, invalid_lines: int) -> None:
    print("COUNT\tTOOL")
    for tool, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"{count}\t{tool}")

    print()
    print(f"total_calls\t{sum(counts.values())}")
    print(f"unique_tools\t{len(counts)}")
    print(f"files_scanned\t{files_scanned}")
    print(f"invalid_lines\t{invalid_lines}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Count top-level tool fields in conversation JSONL logs."
    )
    parser.add_argument(
        "log_dir",
        nargs="?",
        type=Path,
        default=DEFAULT_LOG_DIR,
        help=f"Log directory (default: {DEFAULT_LOG_DIR})",
    )
    args = parser.parse_args()

    if not args.log_dir.is_dir():
        parser.error(f"log directory not found: {args.log_dir}")

    counts, files_scanned, invalid_lines = count_tools(args.log_dir)
    print_report(counts, files_scanned, invalid_lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
