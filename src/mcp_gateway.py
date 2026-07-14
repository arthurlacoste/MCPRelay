#!/usr/bin/env python3

import asyncio
import json
import logging
import os
import secrets
import signal
import subprocess
import threading
import base64
import re
from datetime import datetime, UTC
from typing import Literal
from pathlib import Path

from dotenv import load_dotenv
from fastapi.responses import FileResponse, JSONResponse
from fastmcp import FastMCP
from fastmcp.client import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier
from filesystem_config import get_filesystem_roots
from lightweight_oauth import app as oauth_app
from tool_registry import configurable_tool, is_downstream_enabled
from pydantic import AnyHttpUrl
from starlette.routing import Mount

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / 'config' / '.env')

logging.basicConfig(level=logging.INFO)

LOG_FILE = BASE_DIR / 'logs' / 'mcp_gateway.log'
STREAM_DIR = BASE_DIR / 'logs' / 'commands'
VISION_DIR = BASE_DIR / 'logs' / 'vision'
CONVERSATION_DIR = BASE_DIR / 'logs' / 'conversations'
PUBLIC_SHARES_FILE = BASE_DIR / 'data' / 'public_file_shares.json'
FILESYSTEM_ROOTS = get_filesystem_roots(BASE_DIR)
STREAM_DIR.mkdir(parents=True, exist_ok=True)
VISION_DIR.mkdir(parents=True, exist_ok=True)
CONVERSATION_DIR.mkdir(parents=True, exist_ok=True)
PUBLIC_SHARES_FILE.parent.mkdir(exist_ok=True)

LOCAL_OAUTH_ISSUER = os.getenv(
    'LOCAL_OAUTH_ISSUER',
    'https://hull-envision-bunkbed.ngrok-free.dev/oauth'
)

MCP_BASE_URL = os.getenv(
    'MCP_BASE_URL',
    'https://hull-envision-bunkbed.ngrok-free.dev'
)

MCP_AUDIENCE = os.getenv(
    'MCP_AUDIENCE',
    'https://mcp.local'
)

ENABLE_OAUTH = os.getenv('ENABLE_OAUTH', 'true').lower() == 'true'
CHATGPT_STARTUP_BROWSER_ASSIST = os.getenv(
    'CHATGPT_STARTUP_BROWSER_ASSIST',
    'false',
).lower() in {'1', 'true', 'yes', 'on'}




def append_tool_conversation_event(
    conversation_id: str | None,
    tool: str,
    payload: dict,
):
    if not conversation_id:
        return

    append_conversation_event(conversation_id, {
        'type': 'mcp_call',
        'tool': tool,
        **payload,
    })


def log_action(action: str, payload: dict | None = None):
    entry = {
        'timestamp': datetime.now(UTC).isoformat(),
        'action': action,
        'payload': payload or {}
    }

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def load_public_shares() -> dict:
    if not PUBLIC_SHARES_FILE.exists():
        return {}

    with open(PUBLIC_SHARES_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_public_shares(shares: dict):
    tmp_path = PUBLIC_SHARES_FILE.with_suffix(PUBLIC_SHARES_FILE.suffix + '.tmp')

    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(shares, f, ensure_ascii=False, indent=2)

    tmp_path.replace(PUBLIC_SHARES_FILE)


def public_file_url(share_id: str) -> str:
    return f'{MCP_BASE_URL.rstrip("/")}/public-files/{share_id}'


ALLOWED_CONVERSATION_KINDS = {
    'user_goal', 'plan', 'reasoning_summary', 'assumption',
    'decision', 'risk', 'status', 'summary', 'error', 'todo', 'handoff'
}

ConversationKind = Literal[
    'user_goal', 'plan', 'reasoning_summary', 'assumption',
    'decision', 'risk', 'status', 'summary', 'error', 'todo', 'handoff',
]


def sanitize_conversation_id(conversation_id: str) -> str:
    sanitized = re.sub(r'[^a-zA-Z0-9_.-]', '_', conversation_id).strip('._')
    if not sanitized:
        raise ValueError('conversation_id is invalid')
    return sanitized


def generate_conversation_id() -> str:
    return f"conv_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"


def conversation_log_path(conversation_id: str) -> Path:
    return CONVERSATION_DIR / f"{sanitize_conversation_id(conversation_id)}.jsonl"


def append_conversation_event(conversation_id: str, event: dict) -> Path:
    path = conversation_log_path(conversation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {'timestamp': datetime.now(UTC).isoformat(), **event}
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(payload, ensure_ascii=False) + '\n')
    return path




def conversation_has_start(conversation_id: str) -> bool:
    path = conversation_log_path(conversation_id)
    if not path.exists():
        return False

    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    if json.loads(line).get('type') == 'conversation_start':
                        return True
                except json.JSONDecodeError:
                    continue
    except OSError:
        return False

    return False


def ensure_conversation_started(
    conversation_id: str | None = None,
    chatgpt_url: str | None = None,
    title: str | None = None,
    user_goal: str | None = None,
    initial_instruction: str | None = None,
    source_tool: str | None = None,
) -> dict | None:
    if not conversation_id:
        return None

    safe_id = sanitize_conversation_id(conversation_id)
    if conversation_has_start(safe_id):
        return {
            'ok': True,
            'conversation_id': safe_id,
            'already_started': True,
            'forced': False,
        }

    startup_browser_assist = chatgpt_startup_browser_assist(chatgpt_url)
    log_path = append_conversation_event(safe_id, {
        'type': 'conversation_start',
        'title': title,
        'user_goal': user_goal,
        'initial_instruction': initial_instruction,
        'chatgpt_url': chatgpt_url,
        'startup_browser_assist': startup_browser_assist,
        'forced': True,
        'source_tool': source_tool,
    })
    return {
        'ok': True,
        'conversation_id': safe_id,
        'already_started': False,
        'forced': True,
        'log_path': str(log_path),
        'startup_browser_assist': startup_browser_assist,
    }

def resolve_share_path(path: str) -> Path:
    file_path = Path(path).expanduser()

    if not file_path.is_absolute():
        file_path = (BASE_DIR / file_path)

    resolved = file_path.resolve(strict=True)

    if not resolved.is_file():
        raise ValueError('path must point to an existing file')

    return resolved


mcp_kwargs = {}

if ENABLE_OAUTH:
    token_verifier = JWTVerifier(
        jwks_uri=f'{LOCAL_OAUTH_ISSUER}/jwks.json',
        issuer=LOCAL_OAUTH_ISSUER,
        audience=MCP_AUDIENCE,
    )

    mcp_kwargs['auth'] = RemoteAuthProvider(
        token_verifier=token_verifier,
        authorization_servers=[AnyHttpUrl(LOCAL_OAUTH_ISSUER)],
        base_url=MCP_BASE_URL,
    )

    log_action('oauth_enabled', {
        'issuer': LOCAL_OAUTH_ISSUER,
        'audience': MCP_AUDIENCE,
        'base_url': MCP_BASE_URL,
    })
else:
    log_action('oauth_disabled')


mcp = FastMCP(
    'local-mcp-gateway',
    **mcp_kwargs
)


@oauth_app.get('/public-files/{share_id}')
def serve_public_file(share_id: str):
    shares = load_public_shares()
    share = shares.get(share_id)

    if not share:
        return JSONResponse({'error': 'not_found'}, status_code=404)

    path = Path(share['path'])

    if not path.exists() or not path.is_file():
        return JSONResponse({'error': 'file_missing'}, status_code=404)

    return FileResponse(
        path,
        filename=share.get('download_name') or path.name,
        media_type='application/octet-stream',
    )


mcp._additional_http_routes.append(Mount('/', app=oauth_app, name='oauth'))

filesystem_transport = StdioTransport(
    command='npx',
    args=[
        '-y',
        '@modelcontextprotocol/server-filesystem',
        *FILESYSTEM_ROOTS,
    ]
)

puppeteer_transport = StdioTransport(
    command='npx',
    args=[
        '-y',
        '@modelcontextprotocol/server-puppeteer'
    ]
)

filesystem_client = Client(filesystem_transport)
puppeteer_client = Client(puppeteer_transport)


def get_pyautogui():
    try:
        import pyautogui
    except ImportError as exc:
        raise RuntimeError(
            'pyautogui is not installed. Run start_services.py to install gateway dependencies.'
        ) from exc

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    return pyautogui


def normalize_region(region: dict | None):
    if not region:
        return None

    required = ('x', 'y', 'width', 'height')
    missing = [key for key in required if key not in region]

    if missing:
        raise ValueError(f'missing region fields: {", ".join(missing)}')

    values = tuple(int(region[key]) for key in required)

    if values[2] <= 0 or values[3] <= 0:
        raise ValueError('region width and height must be positive')

    return values


def clamp_duration(duration: float | int | None) -> float:
    if duration is None:
        return 0.0

    return max(0.0, min(float(duration), 10.0))


def validate_button(button: str) -> str:
    if button not in {'left', 'middle', 'right'}:
        raise ValueError('button must be one of: left, middle, right')

    return button


def vision_log_path(prefix: str, suffix: str = 'png') -> Path:
    item_id = datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')
    return VISION_DIR / f'{prefix}_{item_id}.{suffix}'



def chatgpt_startup_browser_assist(chatgpt_url: str | None = None) -> dict:
    """Best-effort startup assist for ChatGPT conversations.

    Disabled by default so starting/logging a conversation never opens or
    focuses Chrome unless explicitly opted in with CHATGPT_STARTUP_BROWSER_ASSIST.
    Conversation-specific redirection can be handled client-side, for example
    by TamperMonkey. This helper is intentionally non-fatal so conversation
    logging continues even if Chrome or macOS GUI automation is unavailable.
    """
    target_url = 'https://chatgpt.com/'

    if not CHATGPT_STARTUP_BROWSER_ASSIST:
        return {
            'ok': True,
            'enabled': False,
            'target_url': target_url,
            'action': 'disabled',
            'opened_new_tab': False,
            'focused_existing_same_url_tab': False,
        }


    safe_target_url = json.dumps(target_url)
    apple_script = '\n'.join([
        f'set targetUrl to {safe_target_url}',
        'set foundTab to false',
        'set foundWindowIndex to 0',
        'set foundTabIndex to 0',
        'tell application "Google Chrome"',
        'activate',
        'if (count of windows) > 0 then',
        'repeat with w from 1 to count of windows',
        'repeat with t from 1 to count of tabs of window w',
        'if URL of tab t of window w is targetUrl then',
        'set foundTab to true',
        'set foundWindowIndex to w',
        'set foundTabIndex to t',
        'exit repeat',
        'end if',
        'end repeat',
        'if foundTab then exit repeat',
        'end repeat',
        'end if',
        'if foundTab then',
        'set active tab index of window foundWindowIndex to foundTabIndex',
        'set index of window foundWindowIndex to 1',
        'return "focused_existing"',
        'else',
        'if (count of windows) = 0 then make new window',
        'tell window 1 to make new tab with properties {URL:targetUrl}',
        'return "opened_new"',
        'end if',
        'end tell',
    ])

    try:
        completed = subprocess.run(
            ['osascript', '-e', apple_script],
            check=False,
            capture_output=True,
            text=True,
        )
        action = completed.stdout.strip()
        return {
            'ok': completed.returncode == 0,
            'target_url': target_url,
            'action': action or 'unknown',
            'opened_new_tab': action == 'opened_new',
            'focused_existing_same_url_tab': action == 'focused_existing',
            'stderr': completed.stderr.strip() if completed.returncode != 0 else '',
        }
    except Exception as exc:
        return {
            'ok': False,
            'error': str(exc),
            'target_url': target_url,
        }


@configurable_tool(mcp)
def conversation_start(
    conversation_id: str | None = None,
    title: str | None = None,
    user_goal: str | None = None,
    initial_instruction: str | None = None,
    chatgpt_url: str | None = None,
) -> dict:
    conversation_id = sanitize_conversation_id(conversation_id or generate_conversation_id())
    ensured = ensure_conversation_started(
        conversation_id=conversation_id,
        chatgpt_url=chatgpt_url,
        title=title,
        user_goal=user_goal,
        initial_instruction=initial_instruction,
        source_tool='conversation_start',
    )
    log_path = conversation_log_path(conversation_id)
    return {
        'conversation_id': conversation_id,
        'log_path': str(log_path),
        'startup_browser_assist': (ensured or {}).get('startup_browser_assist'),
        'already_started': (ensured or {}).get('already_started', False),
        'forced': (ensured or {}).get('forced', False),
        'message': 'Use this conversation_id in subsequent MCP calls.'
    }


@configurable_tool(mcp)
def conversation_note(
    conversation_id: str,
    kind: ConversationKind,
    content: str,
    metadata: dict | None = None,
    chatgpt_url: str | None = None,
) -> dict:
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='conversation_note')
    normalized_kind = kind.strip().lower()
    if normalized_kind not in ALLOWED_CONVERSATION_KINDS:
        raise ValueError(f'invalid kind: {normalized_kind}')

    log_path = append_conversation_event(conversation_id, {
        'type': 'conversation_note',
        'kind': normalized_kind,
        'content': content,
        'metadata': metadata or {},
    })

    return {
        'ok': True,
        'conversation_id': sanitize_conversation_id(conversation_id),
        'log_path': str(log_path),
    }


@configurable_tool(mcp)
def auth_status(conversation_id: str | None = None, chatgpt_url: str | None = None) -> dict:
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='auth_status')
    return {
        'oauth_enabled': ENABLE_OAUTH,
        'issuer': LOCAL_OAUTH_ISSUER,
        'audience': MCP_AUDIENCE,
        'base_url': MCP_BASE_URL,
    }


@configurable_tool(mcp)
def public_file_share(path: str, download_name: str | None = None, conversation_id: str | None = None, chatgpt_url: str | None = None) -> dict:
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='public_file_share')
    resolved = resolve_share_path(path)
    share_id = secrets.token_urlsafe(32)
    shares = load_public_shares()

    shares[share_id] = {
        'path': str(resolved),
        'download_name': download_name or resolved.name,
        'created_at': datetime.now(UTC).isoformat(),
    }
    save_public_shares(shares)

    url = public_file_url(share_id)

    log_action('public_file_share', {
        'share_id': share_id,
        'path': str(resolved),
        'download_name': shares[share_id]['download_name'],
        'url': url,
    })

    return {
        'share_id': share_id,
        'path': str(resolved),
        'url': url,
        'warning': 'Anyone with this URL can download the file until the share is revoked.',
    }


@configurable_tool(mcp)
def public_file_list(conversation_id: str | None = None, chatgpt_url: str | None = None) -> list[dict]:
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='public_file_list')
    shares = load_public_shares()

    return [
        {
            'share_id': share_id,
            'path': share['path'],
            'download_name': share.get('download_name'),
            'created_at': share.get('created_at'),
            'url': public_file_url(share_id),
            'exists': Path(share['path']).is_file(),
        }
        for share_id, share in sorted(shares.items())
    ]


@configurable_tool(mcp)
def public_file_revoke(share_id: str, conversation_id: str | None = None, chatgpt_url: str | None = None) -> dict:
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='public_file_revoke')
    shares = load_public_shares()
    removed = shares.pop(share_id, None)

    if removed is None:
        return {
            'revoked': False,
            'share_id': share_id,
            'message': 'share_id not found',
        }

    save_public_shares(shares)

    log_action('public_file_revoke', {
        'share_id': share_id,
        'path': removed.get('path'),
    })

    return {
        'revoked': True,
        'share_id': share_id,
    }


@configurable_tool(mcp)
async def list_filesystem_available_tools(conversation_id: str | None = None, chatgpt_url: str | None = None) -> str:
    await asyncio.to_thread(ensure_conversation_started, conversation_id, chatgpt_url, source_tool='list_filesystem_available_tools')
    async with filesystem_client:
        tools = await filesystem_client.list_tools()
        return str([tool for tool in tools if is_downstream_enabled('filesystem', tool.name)])


@configurable_tool(mcp)
async def list_puppeteer_available_tools(conversation_id: str | None = None, chatgpt_url: str | None = None) -> str:
    await asyncio.to_thread(ensure_conversation_started, conversation_id, chatgpt_url, source_tool='list_puppeteer_available_tools')
    async with puppeteer_client:
        tools = await puppeteer_client.list_tools()
        return str([tool for tool in tools if is_downstream_enabled('puppeteer', tool.name)])


@configurable_tool(mcp)
async def filesystem_execute_tool(
    name: str,
    arguments: dict = {},
    conversation_id: str | None = None,
    purpose: str | None = None,
    chatgpt_url: str | None = None,
) -> str:
    if not is_downstream_enabled('filesystem', name):
        raise ValueError(f'filesystem tool disabled: {name}')

    tool_arguments = dict(arguments or {})
    embedded_conversation_id = tool_arguments.pop('conversation_id', None)
    embedded_chatgpt_url = tool_arguments.pop('chatgpt_url', None)
    embedded_purpose = tool_arguments.pop('purpose', None)
    conversation_id = conversation_id or embedded_conversation_id
    chatgpt_url = chatgpt_url or embedded_chatgpt_url
    purpose = purpose or embedded_purpose

    await asyncio.to_thread(ensure_conversation_started, conversation_id, chatgpt_url, source_tool='filesystem_execute_tool')
    await asyncio.to_thread(log_action, 'filesystem_execute_tool', {
        'tool': name,
        'arguments': tool_arguments,
        'conversation_id': conversation_id,
        'purpose': purpose,
        'chatgpt_url': chatgpt_url,
    })

    async with filesystem_client:
        result = await filesystem_client.call_tool(name, tool_arguments)
        await asyncio.to_thread(append_tool_conversation_event, conversation_id, 'filesystem_execute_tool', {
            'arguments': {'tool': name, 'purpose': purpose},
            'result_preview': str(result)[:1000],
        })
        return str(result)


@configurable_tool(mcp)
async def puppeteer_execute_tool(name: str, arguments: dict = {}, conversation_id: str | None = None, purpose: str | None = None, chatgpt_url: str | None = None) -> str:
    if not is_downstream_enabled('puppeteer', name):
        raise ValueError(f'puppeteer tool disabled: {name}')

    await asyncio.to_thread(ensure_conversation_started, conversation_id, chatgpt_url, source_tool='puppeteer_execute_tool')
    await asyncio.to_thread(log_action, 'puppeteer_execute_tool', {
        'tool': name,
        'arguments': arguments,
        'conversation_id': conversation_id,
        'purpose': purpose,
    })

    async with puppeteer_client:
        result = await puppeteer_client.call_tool(name, arguments)
        await asyncio.to_thread(append_tool_conversation_event, conversation_id, 'puppeteer_execute_tool', {
            'arguments': {'tool': name, 'purpose': purpose},
            'result_preview': str(result)[:1000],
        })
        return str(result)


@configurable_tool(mcp)
def vision_screen_size(conversation_id: str | None = None, chatgpt_url: str | None = None) -> dict:
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='vision_screen_size')
    pyautogui = get_pyautogui()
    size = pyautogui.size()

    return {
        'width': size.width,
        'height': size.height,
    }


@configurable_tool(mcp)
def vision_screenshot(region: dict | None = None, conversation_id: str | None = None, purpose: str | None = None, chatgpt_url: str | None = None) -> dict:
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='vision_screenshot')
    pyautogui = get_pyautogui()
    normalized_region = normalize_region(region)

    try:
        image = pyautogui.screenshot(region=normalized_region)
    except Exception as exc:
        raise RuntimeError(
            'Could not capture the screen. On macOS, grant Screen Recording '
            'permission to the terminal or service process running this gateway.'
        ) from exc

    path = vision_log_path('screenshot')
    image.save(path)

    log_action('vision_screenshot', {
        'path': str(path),
        'region': region,
    })

    append_tool_conversation_event(conversation_id, 'vision_screenshot', {'path': str(path), 'purpose': purpose})

    return {
        'path': str(path),
        'width': image.width,
        'height': image.height,
        'region': region,
    }


@configurable_tool(mcp)
def vision_screenshot_as_base64(region: dict | None = None, conversation_id: str | None = None, purpose: str | None = None, chatgpt_url: str | None = None) -> dict:
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='vision_screenshot_as_base64')
    pyautogui = get_pyautogui()
    normalized_region = normalize_region(region)

    try:
        image = pyautogui.screenshot(region=normalized_region)
    except Exception as exc:
        raise RuntimeError(
            'Could not capture the screen. On macOS, grant Screen Recording '
            'permission to the terminal or service process running this gateway.'
        ) from exc

    path = vision_log_path('screenshot')
    image.save(path)

    with open(path, 'rb') as f:
        base64_png = base64.b64encode(f.read()).decode('ascii')

    log_action('vision_screenshot_as_base64', {
        'path': str(path),
        'region': region,
    })

    return {
        'path': str(path),
        'width': image.width,
        'height': image.height,
        'region': region,
        'base64_png': base64_png,
    }


@configurable_tool(mcp)
def mouse_position() -> dict:
    pyautogui = get_pyautogui()
    position = pyautogui.position()

    return {
        'x': position.x,
        'y': position.y,
    }


@configurable_tool(mcp)
def mouse_move(x: int, y: int, duration: float = 0.0) -> dict:
    pyautogui = get_pyautogui()
    pyautogui.moveTo(int(x), int(y), duration=clamp_duration(duration))
    position = pyautogui.position()

    log_action('mouse_move', {'x': x, 'y': y, 'duration': duration})

    return {
        'x': position.x,
        'y': position.y,
    }


@configurable_tool(mcp)
def mouse_click_at(
    x: int,
    y: int,
    button: str = 'left',
    clicks: int = 1,
    interval: float = 0.0,
) -> dict:
    pyautogui = get_pyautogui()
    safe_clicks = max(1, min(int(clicks), 10))
    safe_interval = max(0.0, min(float(interval), 5.0))
    safe_button = validate_button(button)

    pyautogui.click(
        x=int(x),
        y=int(y),
        button=safe_button,
        clicks=safe_clicks,
        interval=safe_interval,
    )

    position = pyautogui.position()

    log_action('mouse_click_at', {
        'x': x,
        'y': y,
        'button': safe_button,
        'clicks': safe_clicks,
        'interval': safe_interval,
    })

    return {
        'x': position.x,
        'y': position.y,
        'button': safe_button,
        'clicks': safe_clicks,
    }


@configurable_tool(mcp)
def mouse_click_current(
    button: str = 'left',
    clicks: int = 1,
    interval: float = 0.0,
) -> dict:
    pyautogui = get_pyautogui()
    safe_clicks = max(1, min(int(clicks), 10))
    safe_interval = max(0.0, min(float(interval), 5.0))
    safe_button = validate_button(button)

    pyautogui.click(button=safe_button, clicks=safe_clicks, interval=safe_interval)

    position = pyautogui.position()

    log_action('mouse_click_current', {
        'button': safe_button,
        'clicks': safe_clicks,
        'interval': safe_interval,
    })

    return {
        'x': position.x,
        'y': position.y,
        'button': safe_button,
        'clicks': safe_clicks,
    }


@configurable_tool(mcp)
def mouse_drag(x: int, y: int, duration: float = 0.2, button: str = 'left') -> dict:
    pyautogui = get_pyautogui()
    safe_button = validate_button(button)
    pyautogui.dragTo(int(x), int(y), duration=clamp_duration(duration), button=safe_button)
    position = pyautogui.position()

    log_action('mouse_drag', {
        'x': x,
        'y': y,
        'duration': duration,
        'button': safe_button,
    })

    return {
        'x': position.x,
        'y': position.y,
    }


@configurable_tool(mcp)
def mouse_scroll(clicks: int, x: int | None = None, y: int | None = None) -> dict:
    pyautogui = get_pyautogui()
    safe_clicks = max(-100, min(int(clicks), 100))

    if x is not None and y is not None:
        pyautogui.moveTo(int(x), int(y), duration=0)

    pyautogui.scroll(safe_clicks)
    position = pyautogui.position()

    log_action('mouse_scroll', {
        'clicks': safe_clicks,
        'x': x,
        'y': y,
    })

    return {
        'x': position.x,
        'y': position.y,
        'clicks': safe_clicks,
    }


@configurable_tool(mcp)
def keyboard_type(text: str, interval: float = 0.0) -> dict:
    pyautogui = get_pyautogui()
    safe_interval = max(0.0, min(float(interval), 1.0))
    pyautogui.write(text, interval=safe_interval)

    log_action('keyboard_type', {
        'length': len(text),
        'interval': safe_interval,
    })

    return {
        'typed_characters': len(text),
    }


@configurable_tool(mcp)
def keyboard_press(key: str, presses: int = 1, interval: float = 0.0) -> dict:
    pyautogui = get_pyautogui()
    safe_presses = max(1, min(int(presses), 50))
    safe_interval = max(0.0, min(float(interval), 2.0))
    pyautogui.press(key, presses=safe_presses, interval=safe_interval)

    log_action('keyboard_press', {
        'key': key,
        'presses': safe_presses,
        'interval': safe_interval,
    })

    return {
        'key': key,
        'presses': safe_presses,
    }


@configurable_tool(mcp)
def keyboard_hotkey(keys: list[str], interval: float = 0.0) -> dict:
    if not keys:
        raise ValueError('keys must not be empty')

    pyautogui = get_pyautogui()
    safe_interval = max(0.0, min(float(interval), 2.0))
    pyautogui.hotkey(*keys, interval=safe_interval)

    log_action('keyboard_hotkey', {
        'keys': keys,
        'interval': safe_interval,
    })

    return {
        'keys': keys,
    }


MAX_OUTPUT_CHARS = 50_000
DEFAULT_COMMAND_TIMEOUT_SECONDS = float(os.getenv('MCP_COMMAND_TIMEOUT_SECONDS', '300'))
MAX_CONCURRENT_COMMANDS = max(1, int(os.getenv('MCP_MAX_CONCURRENT_COMMANDS', '4')))
COMMAND_KILL_GRACE_SECONDS = 1.0
COMMAND_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_COMMANDS)


def stream_pipe(pipe, logfile, lines: list, prefix=''):
    for line in iter(pipe.readline, ''):
        formatted = f'{prefix}{line}'

        with open(logfile, 'a', encoding='utf-8') as f:
            f.write(formatted)

        print(formatted, end='')
        lines.append(formatted)

    pipe.close()


def _popen_process_group_options() -> dict:
    if os.name == 'nt':
        return {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
    return {'start_new_session': True}


def terminate_process_tree(process: subprocess.Popen, grace_seconds: float = COMMAND_KILL_GRACE_SECONDS) -> None:
    if process.poll() is not None:
        return

    if os.name == 'nt':
        subprocess.run(
            ['taskkill', '/PID', str(process.pid), '/T', '/F'],
            capture_output=True,
            text=True,
            check=False,
        )
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


@configurable_tool(mcp)
def run_command(
    command: str,
    conversation_id: str | None = None,
    purpose: str | None = None,
    include_output_in_conversation_log: bool = False,
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    chatgpt_url: str | None = None,
) -> str:
    safe_timeout = max(0.1, min(float(timeout_seconds), 86_400.0))

    with COMMAND_SEMAPHORE:
        ensure_conversation_started(conversation_id, chatgpt_url, source_tool='run_command')
        command_id = datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')
        stream_log = STREAM_DIR / f'command_{command_id}.log'

        log_action('run_command_start', {
            'command': command,
            'stream_log': str(stream_log),
            'conversation_id': conversation_id,
            'purpose': purpose,
            'timeout_seconds': safe_timeout,
        })

        with open(stream_log, 'w', encoding='utf-8') as f:
            f.write(f'COMMAND:\n{command}\n\n')

        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
            **_popen_process_group_options(),
        )

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        stdout_thread = threading.Thread(
            target=stream_pipe,
            args=(process.stdout, stream_log, stdout_lines, ''),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=stream_pipe,
            args=(process.stderr, stream_log, stderr_lines, '[stderr] '),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        timed_out = False
        try:
            process.wait(timeout=safe_timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate_process_tree(process)
            process.wait()

        stdout_thread.join(timeout=COMMAND_KILL_GRACE_SECONDS + 1)
        stderr_thread.join(timeout=COMMAND_KILL_GRACE_SECONDS + 1)

        stdout_text = ''.join(stdout_lines)
        stderr_text = ''.join(stderr_lines)
        exit_code = process.returncode

        with open(stream_log, 'a', encoding='utf-8') as f:
            if timed_out:
                f.write(f'\n\nTIMED OUT AFTER: {safe_timeout:g}s\n')
            f.write(f'\nEXIT CODE: {exit_code}\n')

        log_action('run_command_end', {
            'command': command,
            'exit_code': exit_code,
            'stream_log': str(stream_log),
            'timed_out': timed_out,
            'timeout_seconds': safe_timeout,
        })

        append_tool_conversation_event(conversation_id, 'run_command', {
            'arguments': {
                'command': command,
                'purpose': purpose,
                'timeout_seconds': safe_timeout,
            },
            'exit_code': exit_code,
            'timed_out': timed_out,
            'result_ref': f'logs/commands/{stream_log.name}',
            'result_included': include_output_in_conversation_log,
            'output_preview': (
                (stdout_text + '\n' + stderr_text)[:4000]
                if include_output_in_conversation_log else None
            ),
        })

        truncated = False
        if len(stdout_text) > MAX_OUTPUT_CHARS:
            stdout_text = stdout_text[:MAX_OUTPUT_CHARS] + '\n… [stdout truncated]'
            truncated = True
        if len(stderr_text) > MAX_OUTPUT_CHARS:
            stderr_text = stderr_text[:MAX_OUTPUT_CHARS] + '\n… [stderr truncated]'
            truncated = True

        parts = [
            f'COMMAND: {command}',
            f'EXIT CODE: {exit_code}',
        ]
        if timed_out:
            parts.append(f'TIMED OUT AFTER: {safe_timeout:g}s')
        parts.extend(['', 'STDOUT:', stdout_text])

        if stderr_text:
            parts.extend(['', 'STDERR:', stderr_text])

        parts.extend(['', f'Full log: {stream_log}'])
        if truncated:
            parts.append(
                f'\nOutput truncated at {MAX_OUTPUT_CHARS} characters per stream. '
                'See log file for full output.'
            )

        return '\n'.join(parts)


if __name__ == '__main__':
    log_action('gateway_start', {
        'host': '0.0.0.0',
        'port': 8761,
        'oauth_enabled': ENABLE_OAUTH,
    })

    mcp.run(
        transport='http',
        host='0.0.0.0',
        port=8761,
        path='/mcp'
    )
