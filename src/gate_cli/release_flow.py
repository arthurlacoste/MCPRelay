from __future__ import annotations

from collections.abc import Callable


def update_with_lifecycle(
    *,
    is_running: Callable[[], bool],
    confirm: Callable[[str], bool],
    stop: Callable[[], int],
    update: Callable[[], tuple[str, bool]],
    start: Callable[[], int],
):
    was_running = is_running()
    if was_running:
        if not confirm("Gate is running. Stop it and continue? [Y/n] "):
            return None
        if stop() != 0:
            raise RuntimeError("Could not stop Gate before updating.")
    try:
        result = update()
    except Exception:
        if was_running:
            start()
        raise
    if was_running and start() != 0:
        raise RuntimeError("Gate updated, but restart failed.")
    return result
