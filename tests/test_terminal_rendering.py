from io import StringIO

from terminal_rendering import (
    CLEAR_SCREEN,
    SHOW_CURSOR,
    TERMINAL_CLEANUP_SEQUENCE,
    TerminalFrameRenderer,
    restore_terminal_output,
)


def test_frame_renderer_patches_only_changed_rows():
    stream = StringIO()
    renderer = TerminalFrameRenderer(stream)

    renderer.render(["header", "running 1s", "preview"], full=True)
    first = stream.getvalue()
    assert first.count(CLEAR_SCREEN) == 1

    renderer.render(["header", "running 1s", "preview"])
    assert stream.getvalue() == first

    renderer.render(["header", "running 2s", "preview"])
    patch = stream.getvalue()[len(first):]
    assert CLEAR_SCREEN not in patch
    assert "\x1b[2;1H\x1b[2Krunning 2s" in patch
    assert "header" not in patch
    assert "preview" not in patch


def test_frame_renderer_clears_removed_rows_without_full_redraw():
    stream = StringIO()
    renderer = TerminalFrameRenderer(stream)
    renderer.render(["one", "two"], full=True)
    start = len(stream.getvalue())

    renderer.render(["one"])

    patch = stream.getvalue()[start:]
    assert CLEAR_SCREEN not in patch
    assert "\x1b[2;1H\x1b[2K" in patch


def test_frame_renderer_finish_restores_cursor():
    stream = StringIO()
    renderer = TerminalFrameRenderer(stream)
    renderer.render(["live"], full=True)

    renderer.finish()

    assert stream.getvalue().endswith(SHOW_CURSOR)
    assert renderer.lines == ()


def test_terminal_cleanup_disables_mouse_modes_and_alternate_screen():
    stream = StringIO()

    restore_terminal_output(stream, force=True)

    output = stream.getvalue()
    assert output == TERMINAL_CLEANUP_SEQUENCE
    for mode in ("9", "1000", "1002", "1003", "1005", "1006", "1015", "1016"):
        assert f"\x1b[?{mode}l" in output
    for mode in ("47", "1047", "1049"):
        assert f"\x1b[?{mode}l" in output
    assert output.endswith(SHOW_CURSOR)
