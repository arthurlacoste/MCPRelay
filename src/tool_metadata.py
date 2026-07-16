from __future__ import annotations

from typing import Any

READ_ONLY = {
    'readOnlyHint': True,
    'destructiveHint': False,
    'idempotentHint': True,
    'openWorldHint': False,
}
LOCAL_WRITE = {
    'readOnlyHint': False,
    'destructiveHint': False,
    'idempotentHint': False,
    'openWorldHint': False,
}
LOCAL_MUTATION = {
    'readOnlyHint': False,
    'destructiveHint': True,
    'idempotentHint': False,
    'openWorldHint': False,
}
EXTERNAL_ACTION = {
    'readOnlyHint': False,
    'destructiveHint': True,
    'idempotentHint': False,
    'openWorldHint': True,
}
LOCAL_NAVIGATION = {
    'readOnlyHint': False,
    'destructiveHint': False,
    'idempotentHint': False,
    'openWorldHint': False,
}

TOOL_METADATA: dict[str, dict[str, Any]] = {
    'conversation_start': {
        'title': 'Start conversation log',
        'description': 'Create or resume a local MCPRelay conversation log and return its stable conversation ID.',
        'annotations': LOCAL_WRITE,
    },
    'conversation_note': {
        'title': 'Add conversation note',
        'description': 'Append a structured note to an existing local MCPRelay conversation log.',
        'annotations': LOCAL_WRITE,
    },
    'auth_status': {
        'title': 'Get authentication status',
        'description': 'Read the local gateway OAuth configuration and public MCP endpoint status.',
        'annotations': READ_ONLY,
    },
    'public_file_share': {
        'title': 'Share local file publicly',
        'description': 'Create a public download URL for a local file until the share is revoked.',
        'annotations': EXTERNAL_ACTION,
    },
    'public_file_list': {
        'title': 'List public file shares',
        'description': 'List active public file shares and whether their local source files still exist.',
        'annotations': READ_ONLY,
    },
    'public_file_revoke': {
        'title': 'Revoke public file share',
        'description': 'Disable an existing public download URL and remove it from the local share registry.',
        'annotations': EXTERNAL_ACTION,
    },
    'list_filesystem_available_tools': {
        'title': 'List filesystem tools',
        'description': 'List enabled tools exposed by the downstream local filesystem MCP server.',
        'annotations': READ_ONLY,
    },
    'list_puppeteer_available_tools': {
        'title': 'List browser tools',
        'description': 'List enabled tools exposed by the downstream Puppeteer MCP server.',
        'annotations': READ_ONLY,
    },
    'filesystem_execute_tool': {
        'title': 'Execute filesystem tool',
        'description': 'Invoke an enabled downstream filesystem tool against configured local filesystem roots.',
        'annotations': LOCAL_MUTATION,
    },
    'puppeteer_execute_tool': {
        'title': 'Execute browser tool',
        'description': 'Invoke an enabled downstream Puppeteer tool that may navigate or interact with external pages.',
        'annotations': EXTERNAL_ACTION,
    },
    'vision_screen_size': {
        'title': 'Get screen size',
        'description': 'Read the current desktop screen dimensions in pixels.',
        'annotations': READ_ONLY,
    },
    'vision_screenshot': {
        'title': 'Capture screenshot',
        'description': 'Capture the full desktop or a selected region and save it to a local vision log file.',
        'annotations': READ_ONLY,
    },
    'vision_screenshot_as_base64': {
        'title': 'Capture screenshot as base64',
        'description': 'Capture the desktop or a selected region and return the PNG as base64 with its local log path.',
        'annotations': READ_ONLY,
    },
    'mouse_position': {
        'title': 'Get mouse position',
        'description': 'Read the current desktop mouse pointer coordinates.',
        'annotations': READ_ONLY,
    },
    'mouse_move': {
        'title': 'Move mouse',
        'description': 'Move the desktop mouse pointer to absolute screen coordinates without clicking.',
        'annotations': LOCAL_NAVIGATION,
    },
    'mouse_click_at': {
        'title': 'Click at position',
        'description': 'Move to absolute screen coordinates and perform one or more mouse clicks.',
        'annotations': EXTERNAL_ACTION,
    },
    'mouse_click_current': {
        'title': 'Click current position',
        'description': 'Perform one or more mouse clicks at the current desktop pointer position.',
        'annotations': EXTERNAL_ACTION,
    },
    'mouse_drag': {
        'title': 'Drag mouse',
        'description': 'Drag from the current pointer position to absolute screen coordinates.',
        'annotations': EXTERNAL_ACTION,
    },
    'mouse_scroll': {
        'title': 'Scroll screen',
        'description': 'Scroll at the current pointer position or after moving to supplied coordinates.',
        'annotations': LOCAL_NAVIGATION,
    },
    'keyboard_type': {
        'title': 'Type text',
        'description': 'Type text into the currently focused desktop application.',
        'annotations': EXTERNAL_ACTION,
    },
    'keyboard_press': {
        'title': 'Press keyboard key',
        'description': 'Press a keyboard key one or more times in the currently focused desktop application.',
        'annotations': EXTERNAL_ACTION,
    },
    'keyboard_hotkey': {
        'title': 'Press keyboard shortcut',
        'description': 'Press a keyboard shortcut in the currently focused desktop application.',
        'annotations': EXTERNAL_ACTION,
    },
}


def tool_metadata(name: str) -> dict[str, Any]:
    return TOOL_METADATA[name]
