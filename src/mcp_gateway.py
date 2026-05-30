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
from copy import deepcopy
from datetime import datetime, UTC
from typing import Literal
from pathlib import Path

from dotenv import load_dotenv
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastmcp import FastMCP
from fastmcp.client import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier
from lightweight_oauth import app as oauth_app
from pydantic import AnyHttpUrl
from starlette.routing import Mount, Route
from agent_manager import AgentManager, AgentSpec
from agent_manager.deepseek_runtime import (
    OPENINTERPRETER_DEEPSEEK_API_BASE,
    OPENINTERPRETER_DEEPSEEK_V4_MODEL,
    openinterpreter_defaults_for_provider,
    normalize_agent_provider,
    clamp_openinterpreter_timeout,
    compose_deepseek_agent_prompt,
    resolve_openinterpreter_api_key,
    run_openinterpreter_chat,
)
from agent_manager.web import create_agents_app
from agent_metrics import get_metrics_instance

try:
    import yaml
except ImportError:
    yaml = None

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
load_dotenv(BASE_DIR / 'config' / '.env', override=True)

logging.basicConfig(level=logging.INFO)

LOG_FILE = BASE_DIR / 'logs' / 'mcp_gateway.log'
STREAM_DIR = BASE_DIR / 'logs' / 'commands'
VISION_DIR = BASE_DIR / 'logs' / 'vision'
CONVERSATION_DIR = BASE_DIR / 'logs' / 'conversations'
PUBLIC_SHARES_FILE = BASE_DIR / 'data' / 'public_file_shares.json'
DEEPSEEK_AGENT_PREPROMPT_FILE = BASE_DIR / 'config' / 'deepseek_agent_preprompt.md'
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


SETTINGS_FILE = BASE_DIR / 'config' / 'settings.yaml'
_SETTINGS_CACHE: dict | None = None
_SETTINGS_MTIME: float | None = None

DEFAULT_SETTINGS = {
    'version': 1,
    'runtime': {'fail_closed': True, 'expose_settings_tool': True, 'expose_health_limits': True},
    'tools': {
        'global_enabled': True,
        'default_enabled': True,
        'always_allowed': ['auth_status', 'mcp_health_check', 'get_settings', 'reload_settings'],
        'disabled': [],
        'per_tool': {},
    },
    'browser': {'open_chrome': {'enabled': False, 'require_explicit_user_request': True}},
    'conversation': {
        'auto_start_enabled': True,
        'start_tool_enabled': True,
        'start_once_per_conversation': True,
        'storage': {
            'format': 'json',
            'legacy_jsonl_read_enabled': True,
            'legacy_jsonl_write_enabled': False,
            'directory': 'logs/conversations',
            'extension': '.json',
            'atomic_write': True,
            'pretty_print': True,
        },
        'event_policy': {'max_argument_chars': 6000, 'max_result_chars': 12000},
    },
    'payload_limits': {
        'enabled': True,
        'advertise_to_client': True,
        'inbound': {
            'max_tool_argument_bytes': 500000,
            'max_single_string_chars': 120000,
            'reject_oversized_payloads': True,
            'rejection_message': 'Payload too large for MCP DL. Split the content into smaller chunks.',
        },
        'outbound': {'max_text_chars': 120000, 'truncate_large_responses': True},
        'chunks': {'preferred_chunk_chars': 60000, 'hard_chunk_chars': 100000},
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings(force: bool = False) -> dict:
    global _SETTINGS_CACHE, _SETTINGS_MTIME
    try:
        mtime = SETTINGS_FILE.stat().st_mtime
    except FileNotFoundError:
        _SETTINGS_CACHE = deepcopy(DEFAULT_SETTINGS)
        _SETTINGS_MTIME = None
        return _SETTINGS_CACHE

    if not force and _SETTINGS_CACHE is not None and _SETTINGS_MTIME == mtime:
        return _SETTINGS_CACHE

    if yaml is None:
        raise RuntimeError('PyYAML is required to load config/settings.yaml')

    with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
        raw = yaml.safe_load(f) or {}

    _SETTINGS_CACHE = deep_merge(DEFAULT_SETTINGS, raw)
    _SETTINGS_MTIME = mtime
    return _SETTINGS_CACHE


def setting(path: str, default=None):
    current = load_settings()
    for part in path.split('.'):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def get_tool_settings(tool_name: str) -> dict:
    return setting(f'tools.per_tool.{tool_name}', {}) or {}


def tool_config_names(tool_name: str) -> list[str]:
    if tool_name.startswith('mouse_'):
        return [tool_name, 'mouse']
    if tool_name.startswith('keyboard_'):
        return [tool_name, 'keyboard']
    return [tool_name]


def is_tool_enabled(tool_name: str) -> bool:
    return is_named_tool_enabled(tool_config_names(tool_name))


def is_named_tool_enabled(tool_names) -> bool:
    tools = setting('tools', {}) or {}
    names = set(tool_names)
    if names & set(tools.get('always_allowed') or []):
        return True
    if not tools.get('global_enabled', True):
        return False
    if names & set(tools.get('disabled') or []):
        return False
    per_tool_settings = tools.get('per_tool') or {}
    for name in names:
        per_tool = per_tool_settings.get(name)
        if per_tool and per_tool.get('enabled') is False:
            return False
    for name in names:
        per_tool = per_tool_settings.get(name)
        if per_tool and per_tool.get('enabled') is True:
            return True
    return tools.get('default_enabled', True)


def downstream_tool_names(namespace: str, tool_name: str) -> list[str]:
    return [tool_name, f'{namespace}.{tool_name}', f'{namespace}_{tool_name}']


def is_downstream_tool_enabled(namespace: str, tool_name: str) -> bool:
    return is_named_tool_enabled(downstream_tool_names(namespace, tool_name))


def filter_available_tools(tools, namespace: str | None = None):
    filtered = []
    for tool in tools:
        tool_name = getattr(tool, 'name', None)
        if not tool_name:
            filtered.append(tool)
            continue
        enabled = is_downstream_tool_enabled(namespace, tool_name) if namespace else is_tool_visible(tool_name)
        if enabled:
            filtered.append(tool)
    return filtered


TOOL_VISIBILITY_DEPENDENCIES = {
    'list_filesystem_available_tools': ['filesystem_execute_tool'],
    'list_puppeteer_available_tools': ['puppeteer_execute_tool'],
    'vision_screen_size': ['vision_screenshot', 'vision_screenshot_as_base64'],
}


def is_tool_visible(tool_name: str) -> bool:
    if not is_tool_enabled(tool_name):
        return False
    dependencies = TOOL_VISIBILITY_DEPENDENCIES.get(tool_name, [])
    if dependencies and not any(is_tool_enabled(dependency) for dependency in dependencies):
        return False
    return True


def prepare_tool_call(tool_name: str, payload=None, purpose: str | None = None):
    if not is_tool_enabled(tool_name):
        raise RuntimeError(f'Tool disabled by config/settings.yaml: {tool_name}')
    cfg = get_tool_settings(tool_name)
    if cfg.get('requires_purpose') and not (purpose or '').strip():
        raise ValueError(f'purpose is required for tool: {tool_name}')
    enforce_payload_limits(tool_name, payload or {})


def enforce_payload_limits(tool_name: str, payload):
    if not setting('payload_limits.enabled', True):
        return
    encoded = json.dumps(payload, ensure_ascii=False, default=str)
    max_bytes = int(setting('payload_limits.inbound.max_tool_argument_bytes', 500000))
    max_string_chars = int(setting('payload_limits.inbound.max_single_string_chars', 120000))
    reject = bool(setting('payload_limits.inbound.reject_oversized_payloads', True))

    def has_long_string(value) -> bool:
        if isinstance(value, str):
            return len(value) > max_string_chars
        if isinstance(value, dict):
            return any(has_long_string(v) for v in value.values())
        if isinstance(value, list):
            return any(has_long_string(v) for v in value)
        return False

    if reject and (len(encoded.encode('utf-8')) > max_bytes or has_long_string(payload)):
        message = setting('payload_limits.inbound.rejection_message', 'Payload too large for MCP DL.')
        raise ValueError(f'{message} tool={tool_name}, max_bytes={max_bytes}, max_string_chars={max_string_chars}')


def truncate_text_for_settings(text: str, label: str = 'text') -> tuple[str, bool]:
    if not setting('payload_limits.enabled', True):
        return text, False
    max_chars = int(setting('payload_limits.outbound.max_text_chars', 120000))
    if len(text) <= max_chars:
        return text, False
    if not setting('payload_limits.outbound.truncate_large_responses', True):
        return text, False
    return text[:max_chars] + f'\n... [{label} truncated at {max_chars} chars]', True


class ConfigAwareFastMCP(FastMCP):
    async def list_tools(self, *, run_middleware: bool = True):
        tools = await super().list_tools(run_middleware=run_middleware)
        return filter_available_tools(tools)


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


def conversation_storage_dir() -> Path:
    directory = setting('conversation.storage.directory', 'logs/conversations')
    if directory == 'logs/conversations':
        path = CONVERSATION_DIR
    else:
        path = Path(directory)
        if not path.is_absolute():
            path = BASE_DIR / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def conversation_log_path(conversation_id: str) -> Path:
    extension = setting('conversation.storage.extension', '.json')
    return conversation_storage_dir() / f"{sanitize_conversation_id(conversation_id)}{extension}"


def legacy_conversation_log_path(conversation_id: str) -> Path:
    return conversation_storage_dir() / f"{sanitize_conversation_id(conversation_id)}.jsonl"


def read_conversation_events(conversation_id: str) -> list[dict]:
    path = conversation_log_path(conversation_id)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(payload, dict):
                return payload.get('events', [])
            if isinstance(payload, list):
                return payload
        except Exception:
            return []

    legacy_path = legacy_conversation_log_path(conversation_id)
    if setting('conversation.storage.legacy_jsonl_read_enabled', True) and legacy_path.exists():
        events = []
        for line in legacy_path.read_text(encoding='utf-8').splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events
    return []


def write_conversation_events(conversation_id: str, events: list[dict]) -> Path:
    path = conversation_log_path(conversation_id)
    payload = {
        'conversation_id': sanitize_conversation_id(conversation_id),
        'updated_at': datetime.now(UTC).isoformat(),
        'events': events,
    }
    indent = 2 if setting('conversation.storage.pretty_print', True) else None
    text = json.dumps(payload, ensure_ascii=False, indent=indent)
    if setting('conversation.storage.atomic_write', True):
        tmp_path = path.with_suffix(path.suffix + '.tmp')
        tmp_path.write_text(text, encoding='utf-8')
        tmp_path.replace(path)
    else:
        path.write_text(text, encoding='utf-8')
    return path


def append_conversation_event(conversation_id: str, event: dict) -> Path:
    events = read_conversation_events(conversation_id)
    payload = {'timestamp': datetime.now(UTC).isoformat(), **event}
    events.append(payload)
    return write_conversation_events(conversation_id, events)


def conversation_has_start(conversation_id: str) -> bool:
    return any(event.get('type') == 'conversation_start' for event in read_conversation_events(conversation_id))


def ensure_conversation_started(
    conversation_id: str | None = None,
    chatgpt_url: str | None = None,
    title: str | None = None,
    user_goal: str | None = None,
    initial_instruction: str | None = None,
    source_tool: str | None = None,
) -> dict | None:
    if not setting('conversation.auto_start_enabled', True):
        return None
    if source_tool == 'conversation_start' and not setting('conversation.start_tool_enabled', True):
        raise RuntimeError('conversation_start disabled by config/settings.yaml')
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


mcp = ConfigAwareFastMCP(
    'local-mcp-gateway',
    **mcp_kwargs
)

AGENT_MANAGER = AgentManager.from_settings(BASE_DIR, load_settings())
AGENT_MANAGER.recover()
AGENT_MANAGER.start_scheduler_thread()


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


def redirect_agents_root(_request):
    return RedirectResponse('/agents/', status_code=307)


def load_scheduler_config() -> dict:
    config_path = BASE_DIR / 'config' / 'scheduler.yaml'
    if not config_path.exists():
        return {}
    if yaml is None:
        return {}
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def scheduler_health(_request):
    scheduler_config = load_scheduler_config()
    counts = AGENT_MANAGER.store.count_by_status()
    metrics = get_metrics_instance(BASE_DIR, scheduler_config)
    alerts = metrics.check_alerts(scheduler_config)
    running = counts.get('running', 0)
    queued = counts.get('queued', 0)
    failed = counts.get('failed', 0) + counts.get('timeout_soft', 0) + counts.get('timeout_hard', 0)
    payload = {
        'ok': True,
        'mode': 'local',
        'scheduler': {
            'configured': bool(scheduler_config),
            'task_sources': scheduler_config.get('scheduler', {}).get('task_sources', []),
            'retry_enabled': scheduler_config.get('retry', {}).get('enabled', True),
            'max_retry_attempts': scheduler_config.get('retry', {}).get('max_attempts', 3),
        },
        'watchdog': {
            'enabled': scheduler_config.get('watchdog', {}).get('enabled', True),
            'check_interval_seconds': scheduler_config.get('watchdog', {}).get('check_interval_seconds', 300),
            'hard_timeout_seconds': scheduler_config.get('watchdog', {}).get('hard_timeout_seconds', 3600),
            'loop_patterns': len(scheduler_config.get('watchdog', {}).get('patterns', [])),
        },
        'agents': {
            'running': running,
            'queued': queued,
            'failed_or_timed_out': failed,
            'counts': counts,
            'max_running_agents': AGENT_MANAGER.max_running_agents,
        },
        'metrics': {
            'enabled': scheduler_config.get('metrics', {}).get('enabled', True),
            'output_file': str(metrics.output_file),
            'recent_counts_1h': metrics.count_recent_events(hours=1),
            'alerts': alerts,
        },
    }
    return JSONResponse(payload)


if setting('agents.web_enabled', True):
    mcp._additional_http_routes.append(Route('/agents', endpoint=redirect_agents_root, methods=['GET']))
    mcp._additional_http_routes.append(
        Mount(setting('agents.web_path', '/agents'), app=create_agents_app(AGENT_MANAGER), name='agents')
    )

mcp._additional_http_routes.append(Route('/scheduler/health', endpoint=scheduler_health, methods=['GET']))
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
    prepare_tool_call('launch_agent', {'agent_url': agent_url, 'new_window': new_window, 'conversation_id': conversation_id, 'purpose': purpose}, purpose)
    purpose_l = (purpose or '').lower()
    explicit_open = ('open chrome' in purpose_l) or ('ouvrir chrome' in purpose_l)
    if not setting('browser.open_chrome.enabled', False) and not explicit_open:
        raise RuntimeError('Chrome opening is disabled by config/settings.yaml unless purpose explicitly asks to open Chrome.')
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
    prepare_tool_call('conversation_start', {'conversation_id': conversation_id, 'title': title, 'user_goal': user_goal}, None)
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
    prepare_tool_call('conversation_note', {'conversation_id': conversation_id, 'kind': kind, 'content': content, 'metadata': metadata}, None)
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
    prepare_tool_call('auth_status', {}, None)
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='auth_status')
    return {
        'oauth_enabled': ENABLE_OAUTH,
        'issuer': LOCAL_OAUTH_ISSUER,
        'audience': MCP_AUDIENCE,
        'base_url': MCP_BASE_URL,
    }




@mcp.tool()
async def get_settings(conversation_id: str | None = None, chatgpt_url: str | None = None) -> dict:
    prepare_tool_call('get_settings', {}, None)
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='get_settings')
    settings = load_settings()
    return {
        'ok': True,
        'settings_file': str(SETTINGS_FILE),
        'settings': settings,
        'payload_limits': settings.get('payload_limits', {}),
        'tools': settings.get('tools', {}),
        'browser': settings.get('browser', {}),
        'conversation': settings.get('conversation', {}),
        'tampermonkey': settings.get('tampermonkey', {}),
    }


@mcp.tool()
async def reload_settings(conversation_id: str | None = None, chatgpt_url: str | None = None) -> dict:
    prepare_tool_call('reload_settings', {}, None)
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='reload_settings')
    settings = load_settings(force=True)
    return {
        'ok': True,
        'settings_file': str(SETTINGS_FILE),
        'version': settings.get('version'),
        'tools_global_enabled': setting('tools.global_enabled', True),
        'conversation_storage_format': setting('conversation.storage.format', 'json'),
    }


@mcp.tool()
async def mcp_health_check(conversation_id: str | None = None, chatgpt_url: str | None = None) -> dict:
    prepare_tool_call('mcp_health_check', {}, None)
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='mcp_health_check')
    settings = load_settings()
    return {
        'ok': True,
        'oauth': {
            'enabled': ENABLE_OAUTH,
            'issuer': LOCAL_OAUTH_ISSUER,
            'audience': MCP_AUDIENCE,
            'base_url': MCP_BASE_URL,
        },
        'settings': {'file': str(SETTINGS_FILE), 'loaded': True, 'version': settings.get('version')},
        'tools': {
            'global_enabled': setting('tools.global_enabled', True),
            'disabled': setting('tools.disabled', []),
            'always_allowed': setting('tools.always_allowed', []),
        },
        'payload_limits': settings.get('payload_limits', {}),
        'conversation': {
            'storage_format': setting('conversation.storage.format', 'json'),
            'path': str(conversation_storage_dir()),
            'auto_start_enabled': setting('conversation.auto_start_enabled', True),
        },
        'browser': settings.get('browser', {}),
    }

@mcp.tool()
async def public_file_share(path: str, download_name: str | None = None, conversation_id: str | None = None, chatgpt_url: str | None = None) -> dict:
    prepare_tool_call('public_file_share', {'path': path, 'download_name': download_name}, None)
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
    prepare_tool_call('public_file_list', {}, None)
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
    prepare_tool_call('public_file_revoke', {'share_id': share_id}, None)
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
    prepare_tool_call('list_filesystem_available_tools', {}, None)
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='list_filesystem_available_tools')
    async with filesystem_client:
        return str(filter_available_tools(await filesystem_client.list_tools(), 'filesystem'))


@mcp.tool()
async def list_puppeteer_available_tools(conversation_id: str | None = None, chatgpt_url: str | None = None) -> str:
    prepare_tool_call('list_puppeteer_available_tools', {}, None)
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='list_puppeteer_available_tools')
    async with puppeteer_client:
        return str(filter_available_tools(await puppeteer_client.list_tools(), 'puppeteer'))


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

    if not is_downstream_tool_enabled('filesystem', name):
        raise RuntimeError(f'Tool disabled by config/settings.yaml: filesystem.{name}')
    prepare_tool_call('filesystem_execute_tool', {'name': name, 'arguments': tool_arguments, 'conversation_id': conversation_id, 'purpose': purpose}, purpose)
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
    tool_arguments = dict(arguments or {})
    if get_tool_settings('puppeteer_execute_tool').get('strip_meta_arguments', True):
        embedded_conversation_id = tool_arguments.pop('conversation_id', None)
        embedded_chatgpt_url = tool_arguments.pop('chatgpt_url', None)
        embedded_purpose = tool_arguments.pop('purpose', None)
        conversation_id = conversation_id or embedded_conversation_id
        chatgpt_url = chatgpt_url or embedded_chatgpt_url
        purpose = purpose or embedded_purpose
    if not is_downstream_tool_enabled('puppeteer', name):
        raise RuntimeError(f'Tool disabled by config/settings.yaml: puppeteer.{name}')
    prepare_tool_call('puppeteer_execute_tool', {'name': name, 'arguments': tool_arguments, 'conversation_id': conversation_id, 'purpose': purpose}, purpose)
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='puppeteer_execute_tool')
    log_action('puppeteer_execute_tool', {
        'tool': name,
        'arguments': tool_arguments,
        'conversation_id': conversation_id,
        'purpose': purpose,
        'timeout_seconds': timeout_seconds,
    })

    async with puppeteer_client:
        result = await puppeteer_client.call_tool(name, tool_arguments)
        append_tool_conversation_event(conversation_id, 'puppeteer_execute_tool', {
            'arguments': {'tool': name, 'purpose': purpose},
            'result_preview': str(result)[:1000],
        })
        return str(result)


@mcp.tool()
async def vision_screen_size(conversation_id: str | None = None, chatgpt_url: str | None = None) -> dict:
    prepare_tool_call('vision_screen_size', {}, None)
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='vision_screen_size')
    pyautogui = get_pyautogui()
    size = pyautogui.size()

    return {
        'width': size.width,
        'height': size.height,
    }


@mcp.tool()
async def vision_screenshot(region: dict | None = None, conversation_id: str | None = None, purpose: str | None = None, chatgpt_url: str | None = None) -> dict:
    prepare_tool_call('vision_screenshot', {'region': region, 'conversation_id': conversation_id, 'purpose': purpose}, purpose)
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
    prepare_tool_call('vision_screenshot_as_base64', {'region': region, 'conversation_id': conversation_id, 'purpose': purpose}, purpose)
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
    prepare_tool_call('mouse_position', {}, None)
    pyautogui = get_pyautogui()
    position = pyautogui.position()

    return {
        'x': position.x,
        'y': position.y,
    }


@mcp.tool()
async def mouse_move(x: int, y: int, duration: float = 0.0) -> dict:
    prepare_tool_call('mouse_move', {'x': x, 'y': y, 'duration': duration}, None)
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
    prepare_tool_call('mouse_click_at', {'x': x, 'y': y, 'button': button, 'clicks': clicks, 'interval': interval}, None)
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
    prepare_tool_call('mouse_click_current', {'button': button, 'clicks': clicks, 'interval': interval}, None)
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
    prepare_tool_call('mouse_drag', {'x': x, 'y': y, 'duration': duration, 'button': button}, None)
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
    prepare_tool_call('mouse_scroll', {'clicks': clicks, 'x': x, 'y': y}, None)
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
    prepare_tool_call('keyboard_type', {'text': text, 'interval': interval}, None)
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
    prepare_tool_call('keyboard_press', {'key': key, 'presses': presses, 'interval': interval}, None)
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
    prepare_tool_call('keyboard_hotkey', {'keys': keys, 'interval': interval}, None)
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


def stream_pipe(pipe, logfile, lines: list, prefix=''):
    for line in iter(pipe.readline, ''):
        formatted = f'{prefix}{line}'

        with open(logfile, 'a', encoding='utf-8') as f:
            f.write(formatted)

        print(formatted, end='')
        lines.append(formatted)

    pipe.close()


def load_deepseek_agent_preprompt() -> str:
    try:
        return DEEPSEEK_AGENT_PREPROMPT_FILE.read_text(encoding='utf-8').strip()
    except FileNotFoundError:
        return ''


def compose_deepseek_agent_prompt(prompt: str) -> str:
    preprompt = load_deepseek_agent_preprompt()
    user_prompt = prompt.strip()
    if not preprompt:
        return user_prompt
    return preprompt + '\n\n## Mission utilisateur\n\n' + user_prompt


@mcp.tool()
async def deepseek_v4_agent(
    prompt: str,
    conversation_id: str | None = None,
    purpose: str | None = None,
    model: str | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
    provider: str = 'deepseek',
    auto_run: bool = True,
    llm_supports_functions: bool = True,
    context_window: int = 4096,
    max_tokens: int = 200,
    timeout_seconds: int | None = None,
    cwd: str | None = None,
    include_output_in_conversation_log: bool = False,
    chatgpt_url: str | None = None,
) -> dict:
    cfg = get_tool_settings('deepseek_v4_agent')
    if timeout_seconds is None:
        timeout_seconds = cfg.get('timeout_seconds')
    if max_tokens == 200:
        max_tokens = int(cfg.get('max_tokens', max_tokens))
    max_tokens = min(int(max_tokens), int(cfg.get('hard_max_tokens', 6000)))
    if context_window == 4096:
        context_window = int(cfg.get('context_window', context_window))
    context_window = min(int(context_window), int(cfg.get('hard_context_window', 16384)))
    if auto_run is True:
        auto_run = bool(cfg.get('auto_run_default', auto_run))
    if include_output_in_conversation_log is False:
        include_output_in_conversation_log = bool(cfg.get('include_output_in_conversation_log_default', False))
    prepare_tool_call('deepseek_v4_agent', {'prompt': prompt, 'purpose': purpose, 'model': model, 'api_base': api_base, 'auto_run': auto_run, 'context_window': context_window, 'max_tokens': max_tokens, 'cwd': cwd}, purpose)
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='deepseek_v4_agent')

    if not prompt.strip():
        raise ValueError('prompt must not be empty')

    agent_prompt = compose_deepseek_agent_prompt(prompt)
    selected_provider = normalize_agent_provider(provider)
    default_model, default_api_base = openinterpreter_defaults_for_provider(selected_provider)
    selected_model = model or default_model
    selected_api_base = api_base or default_api_base
    selected_api_key = resolve_openinterpreter_api_key(api_key, selected_provider)
    timeout = clamp_openinterpreter_timeout(timeout_seconds, int(cfg.get('hard_timeout_seconds', 1200)))
    working_directory = Path(cwd).expanduser().resolve() if cwd else BASE_DIR
    conversation_arguments = {
        'purpose': purpose,
        'provider': selected_provider,
        'model': selected_model,
        'api_base': selected_api_base,
        'auto_run': auto_run,
        'llm_supports_functions': llm_supports_functions,
        'context_window': context_window,
        'max_tokens': max_tokens,
        'timeout_seconds': timeout,
        'cwd': str(working_directory),
    }

    log_action('deepseek_v4_agent_start', {
        'provider': selected_provider,
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
    append_tool_conversation_event(conversation_id, 'deepseek_v4_agent', {
        'status': 'started',
        'arguments': conversation_arguments,
        'result_included': False,
        'output_preview': None,
        'error': None,
    })

    try:
        chat_payload = await asyncio.wait_for(
            asyncio.to_thread(
                run_openinterpreter_chat,
                prompt=agent_prompt,
                model=selected_model,
                api_base=selected_api_base,
                api_key=selected_api_key,
                auto_run=auto_run,
                provider=selected_provider,
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
    except asyncio.CancelledError:
        log_action('deepseek_v4_agent_cancelled', {
            'model': selected_model,
            'conversation_id': conversation_id,
            'purpose': purpose,
        })
        append_tool_conversation_event(conversation_id, 'deepseek_v4_agent', {
            'status': 'cancelled',
            'arguments': conversation_arguments,
            'exit_code': 130,
            'result_included': False,
            'output_preview': None,
            'error': 'cancelled',
        })
        raise

    stdout_text, stdout_truncated = truncate_text_for_settings(stdout_text, 'stdout')
    stderr_text, stderr_truncated = truncate_text_for_settings(stderr_text, 'stderr')
    truncated = stdout_truncated or stderr_truncated

    result = {
        'ok': ok,
        'provider': selected_provider,
        'provider': selected_provider,
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
        'status': 'completed' if ok else 'failed',
        'arguments': conversation_arguments,
        'exit_code': returncode,
        'result_included': include_output_in_conversation_log,
        'output_preview': (
            (stdout_text + '\n' + stderr_text)[:4000]
            if include_output_in_conversation_log else None
        ),
        'error': error,
    })

    return result


def agent_tool_started(tool_name: str, conversation_id: str | None, arguments: dict):
    append_tool_conversation_event(conversation_id, tool_name, {
        'status': 'started',
        'arguments': arguments,
        'result_included': False,
        'output_preview': None,
        'error': None,
    })


def agent_tool_completed(tool_name: str, conversation_id: str | None, arguments: dict, result: dict, include_result: bool = False):
    append_tool_conversation_event(conversation_id, tool_name, {
        'status': 'completed',
        'arguments': arguments,
        'result': result if include_result else None,
        'result_included': include_result,
        'output_preview': None,
        'error': None,
    })


def agent_tool_error(tool_name: str, conversation_id: str | None, arguments: dict, exc: Exception):
    append_tool_conversation_event(conversation_id, tool_name, {
        'status': 'error',
        'arguments': arguments,
        'result_included': False,
        'output_preview': None,
        'error': str(exc),
    })


@mcp.tool()
async def deepseek_agent_submit(
    prompt: str,
    conversation_id: str | None = None,
    purpose: str | None = None,
    cwd: str | None = None,
    model: str | None = None,
    api_base: str | None = None,
    provider: str = 'deepseek',
    auto_run: bool | None = None,
    llm_supports_functions: bool = True,
    context_window: int | None = None,
    max_tokens: int | None = None,
    wait_timeout_seconds: int | None = None,
    agent_timeout_seconds: int | None = None,
    include_output_in_conversation_log: bool | None = None,
    chatgpt_url: str | None = None,
) -> dict:
    cfg = get_tool_settings('deepseek_agent_submit')
    arguments = {
        'purpose': purpose,
        'cwd': cwd,
        'provider': provider,
        'model': model,
        'api_base': api_base,
        'auto_run': auto_run,
        'llm_supports_functions': llm_supports_functions,
        'context_window': context_window,
        'max_tokens': max_tokens,
        'wait_timeout_seconds': wait_timeout_seconds,
        'agent_timeout_seconds': agent_timeout_seconds,
        'include_output_in_conversation_log': include_output_in_conversation_log,
    }
    prepare_tool_call('deepseek_agent_submit', {'prompt': prompt, **arguments}, purpose)
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='deepseek_agent_submit')
    agent_tool_started('deepseek_agent_submit', conversation_id, arguments)
    try:
        selected_provider = normalize_agent_provider(provider)
        default_model, default_api_base = openinterpreter_defaults_for_provider(selected_provider)
        spec = AgentSpec(
            prompt=prompt,
            provider=selected_provider,
            purpose=purpose,
            cwd=cwd,
            model=model or default_model,
            api_base=api_base or default_api_base,
            auto_run=bool(auto_run) if auto_run is not None else bool(get_tool_settings('deepseek_v4_agent').get('auto_run_default', False)),
            llm_supports_functions=llm_supports_functions,
            context_window=int(context_window or get_tool_settings('deepseek_v4_agent').get('context_window', 8192)),
            max_tokens=int(max_tokens or get_tool_settings('deepseek_v4_agent').get('max_tokens', 4000)),
            wait_timeout_seconds=int(wait_timeout_seconds or cfg.get('default_wait_timeout_seconds', setting('agents.default_wait_timeout_seconds', 10))),
            agent_timeout_seconds=agent_timeout_seconds if agent_timeout_seconds is not None else cfg.get('default_agent_timeout_seconds'),
            conversation_id=conversation_id,
            chatgpt_url=chatgpt_url,
            metadata={
                'source_tool': 'deepseek_agent_submit',
                'include_output_in_conversation_log': (
                    include_output_in_conversation_log
                    if include_output_in_conversation_log is not None
                    else cfg.get('include_output_in_conversation_log_default', False)
                ),
            },
        )
        result = AGENT_MANAGER.submit(spec)
        log_action('deepseek_agent_submit', {'agent_id': result['agent_id'], 'conversation_id': conversation_id, 'purpose': purpose})
        agent_tool_completed('deepseek_agent_submit', conversation_id, arguments, result)
        return result
    except Exception as exc:
        agent_tool_error('deepseek_agent_submit', conversation_id, arguments, exc)
        raise


@mcp.tool()
async def deepseek_agent_list(
    status: str | None = None,
    limit: int = 50,
    include_completed: bool = True,
    conversation_id: str | None = None,
    chatgpt_url: str | None = None,
) -> dict:
    arguments = {'status': status, 'limit': limit, 'include_completed': include_completed}
    prepare_tool_call('deepseek_agent_list', arguments, None)
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='deepseek_agent_list')
    result = AGENT_MANAGER.list(status=status, limit=limit, include_completed=include_completed)
    log_action('deepseek_agent_list', {'status': status, 'limit': limit, 'conversation_id': conversation_id})
    agent_tool_completed('deepseek_agent_list', conversation_id, arguments, {'count': len(result['agents'])})
    return result


@mcp.tool()
async def deepseek_agent_get(
    agent_id: str,
    include_prompt: bool = True,
    include_result: bool = True,
    conversation_id: str | None = None,
    chatgpt_url: str | None = None,
) -> dict:
    arguments = {'agent_id': agent_id, 'include_prompt': include_prompt, 'include_result': include_result}
    prepare_tool_call('deepseek_agent_get', arguments, None)
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='deepseek_agent_get')
    result = AGENT_MANAGER.get(agent_id, include_prompt=include_prompt, include_result=include_result)
    log_action('deepseek_agent_get', {'agent_id': agent_id, 'conversation_id': conversation_id})
    agent_tool_completed('deepseek_agent_get', conversation_id, arguments, {'agent_id': agent_id, 'status': result['agent']['status']})
    return result


@mcp.tool()
async def deepseek_agent_logs(
    agent_id: str,
    stream: Literal["stdout", "stderr", "events"] = "stdout",
    tail: int = 200,
    conversation_id: str | None = None,
    chatgpt_url: str | None = None,
) -> dict:
    cfg = get_tool_settings('deepseek_agent_logs')
    max_tail = int(cfg.get('max_tail_lines', 2000))
    tail = min(max(1, int(tail or cfg.get('default_tail_lines', 200))), max_tail)
    arguments = {'agent_id': agent_id, 'stream': stream, 'tail': tail}
    prepare_tool_call('deepseek_agent_logs', arguments, None)
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='deepseek_agent_logs')
    result = AGENT_MANAGER.logs(agent_id, stream=stream, tail=tail)
    log_action('deepseek_agent_logs', {'agent_id': agent_id, 'stream': stream, 'tail': tail, 'conversation_id': conversation_id})
    agent_tool_completed('deepseek_agent_logs', conversation_id, arguments, {'agent_id': agent_id, 'stream': stream, 'tail': tail})
    return result


@mcp.tool()
async def deepseek_agent_cancel(
    agent_id: str,
    force: bool = False,
    conversation_id: str | None = None,
    purpose: str | None = None,
    chatgpt_url: str | None = None,
) -> dict:
    arguments = {'agent_id': agent_id, 'force': force, 'purpose': purpose}
    prepare_tool_call('deepseek_agent_cancel', arguments, purpose)
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='deepseek_agent_cancel')
    try:
        result = AGENT_MANAGER.cancel(agent_id, force=force)
        log_action('deepseek_agent_cancel', {'agent_id': agent_id, 'force': force, 'conversation_id': conversation_id, 'purpose': purpose})
        agent_tool_completed('deepseek_agent_cancel', conversation_id, arguments, result)
        return result
    except Exception as exc:
        agent_tool_error('deepseek_agent_cancel', conversation_id, arguments, exc)
        raise


@mcp.tool()
async def deepseek_agent_update(
    agent_id: str,
    prompt: str | None = None,
    purpose: str | None = None,
    cwd: str | None = None,
    model: str | None = None,
    api_base: str | None = None,
    context_window: int | None = None,
    max_tokens: int | None = None,
    retry_after_update: bool = False,
    conversation_id: str | None = None,
    chatgpt_url: str | None = None,
) -> dict:
    arguments = {
        'agent_id': agent_id,
        'purpose': purpose,
        'cwd': cwd,
        'provider': provider,
        'model': model,
        'api_base': api_base,
        'context_window': context_window,
        'max_tokens': max_tokens,
        'retry_after_update': retry_after_update,
    }
    prepare_tool_call('deepseek_agent_update', {'prompt': prompt, **arguments}, purpose)
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='deepseek_agent_update')
    try:
        result = AGENT_MANAGER.update(
            agent_id,
            prompt=prompt,
            purpose=purpose,
            cwd=cwd,
            model=model,
            api_base=api_base,
            context_window=context_window,
            max_tokens=max_tokens,
        )
        if retry_after_update:
            retry_result = AGENT_MANAGER.retry(agent_id, clone=True, purpose=purpose)
            result['retry'] = retry_result
        log_action('deepseek_agent_update', {'agent_id': agent_id, 'conversation_id': conversation_id, 'purpose': purpose})
        agent_tool_completed('deepseek_agent_update', conversation_id, arguments, {'agent_id': agent_id, 'retry_created': bool(result.get('retry'))})
        return result
    except Exception as exc:
        agent_tool_error('deepseek_agent_update', conversation_id, arguments, exc)
        raise


@mcp.tool()
async def deepseek_agent_retry(
    agent_id: str,
    prompt_override: str | None = None,
    clone: bool = True,
    conversation_id: str | None = None,
    purpose: str | None = None,
    chatgpt_url: str | None = None,
) -> dict:
    arguments = {'agent_id': agent_id, 'clone': clone, 'purpose': purpose, 'prompt_override': bool(prompt_override)}
    prepare_tool_call('deepseek_agent_retry', {'prompt_override': prompt_override, **arguments}, purpose)
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='deepseek_agent_retry')
    try:
        result = AGENT_MANAGER.retry(agent_id, prompt_override=prompt_override, clone=clone, purpose=purpose)
        log_action('deepseek_agent_retry', {'old_agent_id': agent_id, 'new_agent_id': result['new_agent_id'], 'conversation_id': conversation_id, 'purpose': purpose})
        agent_tool_completed('deepseek_agent_retry', conversation_id, arguments, {
            'old_agent_id': agent_id,
            'new_agent_id': result['new_agent_id'],
            'parent_id': result.get('parent_id'),
        })
        return result
    except Exception as exc:
        agent_tool_error('deepseek_agent_retry', conversation_id, arguments, exc)
        raise


@mcp.tool()
async def deepseek_agent_cleanup(
    older_than_days: int = 14,
    statuses: list[str] | None = None,
    dry_run: bool = True,
    conversation_id: str | None = None,
    purpose: str | None = None,
    chatgpt_url: str | None = None,
) -> dict:
    arguments = {'older_than_days': older_than_days, 'statuses': statuses, 'dry_run': dry_run, 'purpose': purpose}
    prepare_tool_call('deepseek_agent_cleanup', arguments, purpose)
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='deepseek_agent_cleanup')
    try:
        result = AGENT_MANAGER.cleanup(older_than_days=older_than_days, statuses=statuses, dry_run=dry_run)
        log_action('deepseek_agent_cleanup', {'count': result['count'], 'dry_run': dry_run, 'conversation_id': conversation_id, 'purpose': purpose})
        agent_tool_completed('deepseek_agent_cleanup', conversation_id, arguments, {'count': result['count'], 'dry_run': dry_run})
        return result
    except Exception as exc:
        agent_tool_error('deepseek_agent_cleanup', conversation_id, arguments, exc)
        raise


@mcp.tool()
async def deepseek_agent_settings_get(
    conversation_id: str | None = None,
    chatgpt_url: str | None = None,
) -> dict:
    prepare_tool_call('deepseek_agent_settings_get', {}, None)
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='deepseek_agent_settings_get')
    result = AGENT_MANAGER.settings_payload()
    log_action('deepseek_agent_settings_get', {'conversation_id': conversation_id})
    agent_tool_completed('deepseek_agent_settings_get', conversation_id, {}, {'enabled': result['enabled']})
    return result


@mcp.tool()
async def run_command(
    command: str,
    conversation_id: str | None = None,
    purpose: str | None = None,
    include_output_in_conversation_log: bool | None = None,
    timeout_seconds: int | None = None,
    chatgpt_url: str | None = None,
) -> str:
    cfg = get_tool_settings('run_command')
    if include_output_in_conversation_log is None:
        include_output_in_conversation_log = bool(cfg.get('include_output_in_conversation_log_default', False))
    timeout_seconds = int(timeout_seconds or cfg.get('default_timeout_seconds', 30))
    timeout_seconds = min(timeout_seconds, int(cfg.get('hard_timeout_seconds', 120)))
    prepare_tool_call('run_command', {'command': command, 'conversation_id': conversation_id, 'purpose': purpose, 'timeout_seconds': timeout_seconds}, purpose)
    ensure_conversation_started(conversation_id, chatgpt_url, source_tool='run_command')
    command_id = datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')
    stream_log = STREAM_DIR / f'command_{command_id}.log'

    track_created_files = bool(cfg.get('track_created_files', False))
    if track_created_files:
        before_scan = subprocess.run(
            'find /Users/art/Dropbox/dev/myMCP -type f',
            shell=True,
            capture_output=True,
            text=True
        )
        before_files = set(before_scan.stdout.splitlines())
    else:
        before_files = set()

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

    timed_out = False
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait()

    stdout_thread.join()
    stderr_thread.join()

    stdout_text = ''.join(stdout_lines)
    stderr_text = ''.join(stderr_lines)

    if track_created_files:
        after_scan = subprocess.run(
            'find /Users/art/Dropbox/dev/myMCP -type f',
            shell=True,
            capture_output=True,
            text=True
        )
        after_files = set(after_scan.stdout.splitlines())
        created_files = sorted(list(after_files - before_files))
    else:
        created_files = []

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
        'created_files': created_files[:200],
        'timed_out': timed_out,
    })

    append_tool_conversation_event(conversation_id, 'run_command', {
        'arguments': {
            'command': command,
            'purpose': purpose,
        },
        'exit_code': process.returncode,
        'created_files': created_files[:200],
        'timed_out': timed_out,
        'result_ref': str(stream_log),
        'result_included': include_output_in_conversation_log,
        'output_preview': (
            (stdout_text + '\n' + stderr_text)[:4000]
            if include_output_in_conversation_log else None
        ),
    })

    stdout_text, stdout_truncated = truncate_text_for_settings(stdout_text, 'stdout')
    stderr_text, stderr_truncated = truncate_text_for_settings(stderr_text, 'stderr')
    truncated = stdout_truncated or stderr_truncated

    parts = [
        f'EXIT CODE: {process.returncode}',
        f'TIMED OUT: {timed_out}',
        f'LOG FILE: {stream_log}',
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
        parts.append('\n⚠️  Output truncated by payload_limits.outbound.max_text_chars. See log file for full output.')

    return '\n'.join(parts)

# settings yaml late override
def conversation_storage_dir() -> Path:
    directory = setting('conversation.storage.directory', 'logs/conversations')
    if directory == 'logs/conversations':
        path = CONVERSATION_DIR
    else:
        path = Path(directory)
        if not path.is_absolute():
            path = BASE_DIR / path
    path.mkdir(parents=True, exist_ok=True)
    return path


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
