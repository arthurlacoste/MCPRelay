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
    if was_running and not confirm("Gate is running. Stop it and continue? [Y/n] "):
        return None

    result = update()

    if was_running:
        if stop() != 0:
            raise RuntimeError("Gate was updated, but the running instance could not be stopped.")
        if start() != 0:
            raise RuntimeError("Gate updated, but restart failed.")
    return result
