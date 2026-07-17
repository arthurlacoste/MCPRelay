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
EXTERNAL_ACTION = {
    'readOnlyHint': False,
    'destructiveHint': True,
    'idempotentHint': False,
    'openWorldHint': True,
}

TOOL_METADATA: dict[str, dict[str, Any]] = {
    'conversation_start': {
        'title': 'Start conversation log',
        'description': 'Create or resume a local Gate conversation log and return its stable conversation ID.',
        'annotations': LOCAL_WRITE,
    },
    'conversation_note': {
        'title': 'Add conversation note',
        'description': 'Append a structured note to an existing local Gate conversation log.',
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
}


def tool_metadata(name: str) -> dict[str, Any]:
    return TOOL_METADATA[name]
