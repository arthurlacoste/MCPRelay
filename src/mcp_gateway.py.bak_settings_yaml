#!/usr/bin/env python3

import json
import logging
import os
import secrets
import subprocess
import threading
import base64
import re
import asyncio
import contextlib
import io
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
from lightweight_oauth import app as oauth_app
from pydantic import AnyHttpUrl
from starlette.routing import Mount

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
load_dotenv(BASE_DIR / 'config' / '.env', override=True)

logging.basicConfig(level=logging.INFO)

LOG_FILE = BASE_DIR / 'logs' / 'mcp_gateway.log'
STREAM_DIR = BASE_DIR / 'logs' / 'commands'
VISION_DIR = BASE_DIR / 'logs' / 'vision'
CONVERSATION_DIR = BASE_DIR / 'logs' / 'conversations'
PUBLIC_SHARES_FILE = BASE_DIR / 'data' / 'public_file_shares.json'
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
        '/Users/art/Dropbox/dev/'
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

    Opens or focuses the ChatGPT home page. Conversation-specific
    redirection can be handled client-side, for example by TamperMonkey. This helper is intentionally non-fatal so conversation logging
    continues even if Chrome or macOS GUI automation is unavailable.
    """
    # Always open/focus the ChatGPT home page. Any conversation-specific
    # redirection is handled client-side, for example by TamperMonkey.
    target_url = 'https://chatgpt.com/'

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


@mcp.tool()
async def launch_agent(
    agent_url: str,
    new_window: bool = False,
    conversation_id: str | None = None,
    purpose: str | None = None,
    chatgpt_url: str | None = None,
) -> dict:
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='launch_agent')

    safe_target_url = json.dumps(agent_url)
    mode = 'window' if new_window else 'tab'

    apple_script = '\n'.join([
        f'set targetUrl to {safe_target_url}',
        f'set openMode to "{mode}"',
        'tell application "Google Chrome"',
        'activate',
        'if openMode is "window" then',
        'make new window',
        'set URL of active tab of front window to targetUrl',
        'return "opened_window"',
        'else',
        'if (count of windows) = 0 then make new window',
        'tell front window to make new tab with properties {URL:targetUrl}',
        'return "opened_tab"',
        'end if',
        'end tell',
    ])

    completed = subprocess.run(
        ['osascript', '-e', apple_script],
        check=False,
        capture_output=True,
        text=True,
    )

    result = {
        'ok': completed.returncode == 0,
        'agent_url': agent_url,
        'mode': mode,
        'action': completed.stdout.strip() or 'unknown',
        'stderr': completed.stderr.strip(),
    }

    log_action('launch_agent', {
        'agent_url': agent_url,
        'mode': mode,
        'conversation_id': conversation_id,
        'purpose': purpose,
        **result,
    })

    append_tool_conversation_event(conversation_id, 'launch_agent', {
        'arguments': {
            'agent_url': agent_url,
            'mode': mode,
            'purpose': purpose,
        },
        'result_preview': str(result)[:1000],
    })

    return result


@mcp.tool()
async def conversation_start(
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


@mcp.tool()
async def conversation_note(
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


@mcp.tool()
async def auth_status(conversation_id: str | None = None, chatgpt_url: str | None = None) -> dict:
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='auth_status')
    return {
        'oauth_enabled': ENABLE_OAUTH,
        'issuer': LOCAL_OAUTH_ISSUER,
        'audience': MCP_AUDIENCE,
        'base_url': MCP_BASE_URL,
    }


@mcp.tool()
async def public_file_share(path: str, download_name: str | None = None, conversation_id: str | None = None, chatgpt_url: str | None = None) -> dict:
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


@mcp.tool()
async def public_file_list(conversation_id: str | None = None, chatgpt_url: str | None = None) -> list[dict]:
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


@mcp.tool()
async def public_file_revoke(share_id: str, conversation_id: str | None = None, chatgpt_url: str | None = None) -> dict:
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


@mcp.tool()
async def list_filesystem_available_tools(conversation_id: str | None = None, chatgpt_url: str | None = None) -> str:
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='list_filesystem_available_tools')
    async with filesystem_client:
        return str(await filesystem_client.list_tools())


@mcp.tool()
async def list_puppeteer_available_tools(conversation_id: str | None = None, chatgpt_url: str | None = None) -> str:
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='list_puppeteer_available_tools')
    async with puppeteer_client:
        return str(await puppeteer_client.list_tools())


@mcp.tool()
async def filesystem_execute_tool(
    name: str,
    arguments: dict = {},
    conversation_id: str | None = None,
    purpose: str | None = None,
    chatgpt_url: str | None = None,
) -> str:
    tool_arguments = dict(arguments or {})
    embedded_conversation_id = tool_arguments.pop('conversation_id', None)
    embedded_chatgpt_url = tool_arguments.pop('chatgpt_url', None)
    embedded_purpose = tool_arguments.pop('purpose', None)
    conversation_id = conversation_id or embedded_conversation_id
    chatgpt_url = chatgpt_url or embedded_chatgpt_url
    purpose = purpose or embedded_purpose

    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='filesystem_execute_tool')
    log_action('filesystem_execute_tool', {
        'tool': name,
        'arguments': tool_arguments,
        'conversation_id': conversation_id,
        'purpose': purpose,
        'chatgpt_url': chatgpt_url,
    })

    async with filesystem_client:
        result = await filesystem_client.call_tool(name, tool_arguments)
        append_tool_conversation_event(conversation_id, 'filesystem_execute_tool', {
            'arguments': {'tool': name, 'purpose': purpose},
            'result_preview': str(result)[:1000],
        })
        return str(result)


@mcp.tool()
async def puppeteer_execute_tool(name: str, arguments: dict = {}, conversation_id: str | None = None, purpose: str | None = None, chatgpt_url: str | None = None) -> str:
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='puppeteer_execute_tool')
    log_action('puppeteer_execute_tool', {
        'tool': name,
        'arguments': arguments,
        'conversation_id': conversation_id,
        'purpose': purpose,
    })

    async with puppeteer_client:
        result = await puppeteer_client.call_tool(name, arguments)
        append_tool_conversation_event(conversation_id, 'puppeteer_execute_tool', {
            'arguments': {'tool': name, 'purpose': purpose},
            'result_preview': str(result)[:1000],
        })
        return str(result)


@mcp.tool()
async def vision_screen_size(conversation_id: str | None = None, chatgpt_url: str | None = None) -> dict:
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='vision_screen_size')
    pyautogui = get_pyautogui()
    size = pyautogui.size()

    return {
        'width': size.width,
        'height': size.height,
    }


@mcp.tool()
async def vision_screenshot(region: dict | None = None, conversation_id: str | None = None, purpose: str | None = None, chatgpt_url: str | None = None) -> dict:
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


@mcp.tool()
async def vision_screenshot_as_base64(region: dict | None = None, conversation_id: str | None = None, purpose: str | None = None, chatgpt_url: str | None = None) -> dict:
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


@mcp.tool()
async def mouse_position() -> dict:
    pyautogui = get_pyautogui()
    position = pyautogui.position()

    return {
        'x': position.x,
        'y': position.y,
    }


@mcp.tool()
async def mouse_move(x: int, y: int, duration: float = 0.0) -> dict:
    pyautogui = get_pyautogui()
    pyautogui.moveTo(int(x), int(y), duration=clamp_duration(duration))
    position = pyautogui.position()

    log_action('mouse_move', {'x': x, 'y': y, 'duration': duration})

    return {
        'x': position.x,
        'y': position.y,
    }


@mcp.tool()
async def mouse_click_at(
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


@mcp.tool()
async def mouse_click_current(
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


@mcp.tool()
async def mouse_drag(x: int, y: int, duration: float = 0.2, button: str = 'left') -> dict:
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


@mcp.tool()
async def mouse_scroll(clicks: int, x: int | None = None, y: int | None = None) -> dict:
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


@mcp.tool()
async def keyboard_type(text: str, interval: float = 0.0) -> dict:
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


@mcp.tool()
async def keyboard_press(key: str, presses: int = 1, interval: float = 0.0) -> dict:
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


@mcp.tool()
async def keyboard_hotkey(keys: list[str], interval: float = 0.0) -> dict:
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
OPENINTERPRETER_OUTPUT_CHARS = 50_000
OPENINTERPRETER_DEFAULT_TIMEOUT_SECONDS = 300
OPENINTERPRETER_DEEPSEEK_V4_MODEL = os.getenv(
    'OPENINTERPRETER_DEEPSEEK_V4_MODEL',
    'openai/deepseek-chat',
)
OPENINTERPRETER_DEEPSEEK_API_BASE = os.getenv(
    'OPENINTERPRETER_DEEPSEEK_API_BASE',
    'https://api.deepseek.com/v1',
)
OPENINTERPRETER_RUN_LOCK = threading.Lock()


def stream_pipe(pipe, logfile, lines: list, prefix=''):
    for line in iter(pipe.readline, ''):
        formatted = f'{prefix}{line}'

        with open(logfile, 'a', encoding='utf-8') as f:
            f.write(formatted)

        print(formatted, end='')
        lines.append(formatted)

    pipe.close()


def clamp_openinterpreter_timeout(timeout_seconds: int | None) -> int:
    if timeout_seconds is None:
        return OPENINTERPRETER_DEFAULT_TIMEOUT_SECONDS

    return max(1, min(int(timeout_seconds), 3600))


def resolve_openinterpreter_api_key(api_key: str | None = None) -> str | None:
    return (
        api_key
        or os.environ.get('DEEPSEEK_API_KEY')
        or os.environ.get('OPENAI_API_KEY')
        or os.environ.get('OPENAI_ADMIN_KEY')
    )


def run_openinterpreter_chat(
    prompt: str,
    model: str,
    api_base: str,
    api_key: str | None,
    auto_run: bool,
    llm_supports_functions: bool,
    context_window: int,
    max_tokens: int,
    cwd: Path,
) -> dict:
    try:
        from interpreter import interpreter
    except ImportError as exc:
        raise RuntimeError(
            'OpenInterpreter is not installed in the gateway Python environment. '
            'Install it in the same venv that runs src/mcp_gateway.py.'
        ) from exc

    selected_api_key = resolve_openinterpreter_api_key(api_key)
    interpreter.llm.model = model
    interpreter.llm.api_base = api_base
    interpreter.llm.api_key = selected_api_key
    interpreter.auto_run = auto_run
    interpreter.disable_telemetry = True
    interpreter.llm.context_window = int(context_window)
    interpreter.llm.max_tokens = int(max_tokens)

    if hasattr(interpreter.llm, 'supports_functions'):
        interpreter.llm.supports_functions = llm_supports_functions

    stdout = io.StringIO()
    stderr = io.StringIO()

    with OPENINTERPRETER_RUN_LOCK:
        previous_cwd = Path.cwd()
        previous_openai_api_key = os.environ.get('OPENAI_API_KEY')
        previous_deepseek_api_key = os.environ.get('DEEPSEEK_API_KEY')
        os.chdir(cwd)
        try:
            if selected_api_key:
                os.environ['OPENAI_API_KEY'] = selected_api_key
                os.environ['DEEPSEEK_API_KEY'] = selected_api_key

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                chat_result = interpreter.chat(prompt)
        finally:
            if previous_openai_api_key is None:
                os.environ.pop('OPENAI_API_KEY', None)
            else:
                os.environ['OPENAI_API_KEY'] = previous_openai_api_key

            if previous_deepseek_api_key is None:
                os.environ.pop('DEEPSEEK_API_KEY', None)
            else:
                os.environ['DEEPSEEK_API_KEY'] = previous_deepseek_api_key

            os.chdir(previous_cwd)

    return {
        'stdout': stdout.getvalue(),
        'stderr': stderr.getvalue(),
        'chat_result': chat_result,
    }


@mcp.tool()
async def deepseek_v4_agent(
    prompt: str,
    conversation_id: str | None = None,
    purpose: str | None = None,
    model: str | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
    auto_run: bool = True,
    llm_supports_functions: bool = True,
    context_window: int = 4096,
    max_tokens: int = 200,
    timeout_seconds: int | None = None,
    cwd: str | None = None,
    include_output_in_conversation_log: bool = False,
    chatgpt_url: str | None = None,
) -> dict:
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='deepseek_v4_agent')

    if not prompt.strip():
        raise ValueError('prompt must not be empty')

    selected_model = model or OPENINTERPRETER_DEEPSEEK_V4_MODEL
    selected_api_base = api_base or OPENINTERPRETER_DEEPSEEK_API_BASE
    selected_api_key = resolve_openinterpreter_api_key(api_key)
    timeout = clamp_openinterpreter_timeout(timeout_seconds)
    working_directory = Path(cwd).expanduser().resolve() if cwd else BASE_DIR

    log_action('deepseek_v4_agent_start', {
        'model': selected_model,
        'api_base': selected_api_base,
        'auto_run': auto_run,
        'llm_supports_functions': llm_supports_functions,
        'context_window': context_window,
        'max_tokens': max_tokens,
        'timeout_seconds': timeout,
        'cwd': str(working_directory),
        'conversation_id': conversation_id,
        'purpose': purpose,
    })

    try:
        chat_payload = await asyncio.wait_for(
            asyncio.to_thread(
                run_openinterpreter_chat,
                prompt=prompt,
                model=selected_model,
                api_base=selected_api_base,
                api_key=selected_api_key,
                auto_run=auto_run,
                llm_supports_functions=llm_supports_functions,
                context_window=context_window,
                max_tokens=max_tokens,
                cwd=working_directory,
            ),
            timeout=timeout,
        )
        stdout_text = chat_payload['stdout']
        stderr_text = chat_payload['stderr']
        chat_result = chat_payload['chat_result']
        ok = True
        error = None
        returncode = 0
    except RuntimeError as exc:
        stdout_text = ''
        stderr_text = str(exc)
        chat_result = None
        ok = False
        error = 'openinterpreter_not_installed'
        returncode = 1
    except TimeoutError as exc:
        stdout_text = ''
        stderr_text = str(exc)
        chat_result = None
        ok = False
        error = 'timeout'
        returncode = 124

    truncated = False
    if len(stdout_text) > OPENINTERPRETER_OUTPUT_CHARS:
        stdout_text = stdout_text[:OPENINTERPRETER_OUTPUT_CHARS] + '\n... [stdout truncated]'
        truncated = True

    if len(stderr_text) > OPENINTERPRETER_OUTPUT_CHARS:
        stderr_text = stderr_text[:OPENINTERPRETER_OUTPUT_CHARS] + '\n... [stderr truncated]'
        truncated = True

    result = {
        'ok': ok,
        'model': selected_model,
        'api_base': selected_api_base,
        'cwd': str(working_directory),
        'exit_code': returncode,
        'stdout': stdout_text,
        'stderr': stderr_text,
        'chat_result': chat_result,
        'truncated': truncated,
    }

    if error:
        result['error'] = error

    log_action('deepseek_v4_agent_end', {
        'model': selected_model,
        'exit_code': returncode,
        'ok': ok,
        'error': error,
        'truncated': truncated,
        'conversation_id': conversation_id,
        'purpose': purpose,
    })

    append_tool_conversation_event(conversation_id, 'deepseek_v4_agent', {
        'arguments': {
            'purpose': purpose,
            'model': selected_model,
            'api_base': selected_api_base,
            'auto_run': auto_run,
            'llm_supports_functions': llm_supports_functions,
            'context_window': context_window,
            'max_tokens': max_tokens,
            'timeout_seconds': timeout,
            'cwd': str(working_directory),
        },
        'exit_code': returncode,
        'result_included': include_output_in_conversation_log,
        'output_preview': (
            (stdout_text + '\n' + stderr_text)[:4000]
            if include_output_in_conversation_log else None
        ),
        'error': error,
    })

    return result


@mcp.tool()
async def run_command(
    command: str,
    conversation_id: str | None = None,
    purpose: str | None = None,
    include_output_in_conversation_log: bool = False,
    chatgpt_url: str | None = None,
) -> str:
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='run_command')
    command_id = datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')
    stream_log = STREAM_DIR / f'command_{command_id}.log'

    before_scan = subprocess.run(
        'find /Users/art/Dropbox/dev -type f',
        shell=True,
        capture_output=True,
        text=True
    )

    before_files = set(before_scan.stdout.splitlines())

    log_action('run_command_start', {
        'command': command,
        'stream_log': str(stream_log),
        'conversation_id': conversation_id,
        'purpose': purpose,
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
        universal_newlines=True
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    stdout_thread = threading.Thread(
        target=stream_pipe,
        args=(process.stdout, stream_log, stdout_lines, '')
    )

    stderr_thread = threading.Thread(
        target=stream_pipe,
        args=(process.stderr, stream_log, stderr_lines, '[stderr] ')
    )

    stdout_thread.start()
    stderr_thread.start()

    process.wait()

    stdout_thread.join()
    stderr_thread.join()

    stdout_text = ''.join(stdout_lines)
    stderr_text = ''.join(stderr_lines)

    after_scan = subprocess.run(
        'find /Users/art/Dropbox/dev -type f',
        shell=True,
        capture_output=True,
        text=True
    )

    after_files = set(after_scan.stdout.splitlines())
    created_files = sorted(list(after_files - before_files))

    with open(stream_log, 'a', encoding='utf-8') as f:
        f.write(f'\n\nEXIT CODE: {process.returncode}\n')

        if created_files:
            f.write('\nCREATED FILES:\n')
            f.write('\n'.join(created_files[:200]))
            f.write('\n')

    log_action('run_command_end', {
        'command': command,
        'exit_code': process.returncode,
        'stream_log': str(stream_log),
        'created_files': created_files[:200]
    })

    append_tool_conversation_event(conversation_id, 'run_command', {
        'arguments': {
            'command': command,
            'purpose': purpose,
        },
        'exit_code': process.returncode,
        'created_files': created_files[:200],
        'result_ref': str(stream_log),
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
        f'EXIT CODE: {process.returncode}',
        '',
        'STDOUT:',
        stdout_text,
    ]

    if stderr_text:
        parts.append('')
        parts.append('STDERR:')
        parts.append(stderr_text)

    if created_files:
        parts.append('')
        parts.append(f'CREATED FILES ({len(created_files)}):')
        parts.extend(created_files[:50])


    if truncated:
        parts.append(f'\n⚠️  Output truncated at {MAX_OUTPUT_CHARS} characters per stream. See log file for full output.')

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
