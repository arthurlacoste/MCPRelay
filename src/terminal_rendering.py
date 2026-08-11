from __future__ import annotations

import sys
from typing import TextIO

CLEAR_SCREEN = "\x1b[2J\x1b[H"
ERASE_LINE = "\x1b[2K"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
RESET_STYLE = "\x1b[0m"

# Disable terminal modes that can leak into the parent shell after an abrupt TUI exit.
TERMINAL_CLEANUP_SEQUENCE = (
    RESET_STYLE
    + "\x1b[?9l"
    + "\x1b[?1000l"
    + "\x1b[?1002l"
    + "\x1b[?1003l"
    + "\x1b[?1005l"
    + "\x1b[?1006l"
    + "\x1b[?1015l"
    + "\x1b[?1016l"
    + "\x1b[?47l"
    + "\x1b[?1047l"
    + "\x1b[?1049l"
    + SHOW_CURSOR
)


class TerminalFrameRenderer:
    """Patch only terminal rows whose rendered text changed."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stdout
        self._lines: list[str] = []

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(self._lines)

    def reset(self) -> None:
        self._lines = []

    def render(self, lines: list[str], *, full: bool = False) -> None:
        next_lines = [str(line) for line in lines]
        if full or not self._lines:
            payload = HIDE_CURSOR + CLEAR_SCREEN + "\n".join(next_lines)
            if next_lines:
                payload += "\n"
            self.stream.write(payload)
            self.stream.flush()
            self._lines = next_lines
            return

        patches: list[str] = []
        row_count = max(len(self._lines), len(next_lines))
        for index in range(row_count):
            previous = self._lines[index] if index < len(self._lines) else None
            current = next_lines[index] if index < len(next_lines) else ""
            if previous == current:
                continue
            patches.append(f"\x1b[{index + 1};1H{ERASE_LINE}{current}")

        if patches:
            self.stream.write(HIDE_CURSOR + "".join(patches))
            self.stream.flush()
        self._lines = next_lines

    def finish(self) -> None:
        restore_terminal_output(self.stream, force=True)
        self.reset()


def restore_terminal_output(stream: TextIO | None = None, *, force: bool = False) -> None:
    """Best-effort cleanup for terminal modes left behind by an interrupted TUI."""
    stream = stream or sys.stdout
    try:
        if not force and hasattr(stream, "isatty") and not stream.isatty():
            return
        stream.write(TERMINAL_CLEANUP_SEQUENCE)
        stream.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
