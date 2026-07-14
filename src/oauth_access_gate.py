import html
import ipaddress
import secrets
import threading
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

PENDING_TTL_SECONDS = 300
RATE_LIMIT_WINDOW_SECONDS = 60
MAX_PENDING_REQUESTS = 1000
MAX_PENDING_PER_SOURCE = 20
MAX_RATE_LIMIT_ADDRESSES = 10000


@dataclass
class PendingRequest:
    parameters: dict
    source: str
    created_at: float


@dataclass
class FailureWindow:
    started_at: float
    count: int


def trusted_proxy_networks(value: str) -> tuple:
    networks = []
    for item in value.split(","):
        item = item.strip()
        if item:
            networks.append(ipaddress.ip_network(item, strict=False))
    return tuple(networks)


def client_address(peer: str, forwarded_for: str, trusted_networks: tuple) -> str:
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if not any(peer_ip in network for network in trusted_networks):
        return str(peer_ip)
    chain = []
    for item in forwarded_for.split(","):
        try:
            chain.append(ipaddress.ip_address(item.strip()))
        except ValueError:
            return str(peer_ip)
    for candidate in reversed(chain):
        if not any(candidate in network for network in trusted_networks):
            return str(candidate)
    return str(peer_ip)


class OAuthAccessGate:
    def __init__(self):
        self.pending = {}
        self.failures = {}
        self.lock = threading.Lock()
        self.hasher = PasswordHasher()

    def reset(self):
        with self.lock:
            self.pending.clear()
            self.failures.clear()

    def create(self, parameters: dict, source: str) -> str | None:
        now = time.time()
        request_id = secrets.token_urlsafe(32)
        with self.lock:
            self._purge(now)
            source_count = sum(item.source == source for item in self.pending.values())
            if len(self.pending) >= MAX_PENDING_REQUESTS or source_count >= MAX_PENDING_PER_SOURCE:
                return None
            self.pending[request_id] = PendingRequest(parameters, source, now)
        return request_id

    def get(self, request_id: str) -> PendingRequest | None:
        now = time.time()
        with self.lock:
            self._purge(now)
            return self.pending.get(request_id)

    def consume(self, request_id: str) -> PendingRequest | None:
        now = time.time()
        with self.lock:
            self._purge(now)
            return self.pending.pop(request_id, None)

    def authenticate(self, address: str, maximum: int, secret_hash: str, secret: str) -> str:
        now = time.time()
        with self.lock:
            self._purge_failures(now)
            window = self._failure_window(address, now)
            if window and window.count >= maximum:
                return "limited"
            if not window and len(self.failures) >= MAX_RATE_LIMIT_ADDRESSES:
                return "limited"
            if not secret_hash.startswith("$argon2id$"):
                return "configuration_error"
            try:
                if self.hasher.verify(secret_hash, secret):
                    self.failures.pop(address, None)
                    return "valid"
            except VerifyMismatchError:
                pass
            except (InvalidHashError, VerificationError):
                return "configuration_error"
            if window:
                window.count += 1
            else:
                self.failures[address] = FailureWindow(now, 1)
            return "invalid"

    def _failure_window(self, address: str, now: float) -> FailureWindow | None:
        window = self.failures.get(address)
        if window and now - window.started_at < RATE_LIMIT_WINDOW_SECONDS:
            return window
        self.failures.pop(address, None)
        return None

    def _purge_failures(self, now: float):
        expired = [
            key for key, value in self.failures.items()
            if now - value.started_at >= RATE_LIMIT_WINDOW_SECONDS
        ]
        for key in expired:
            self.failures.pop(key, None)

    def _purge(self, now: float):
        expired = [
            key for key, value in self.pending.items()
            if now - value.created_at > PENDING_TTL_SECONDS
        ]
        for key in expired:
            self.pending.pop(key, None)


def login_page(request_id: str, details: dict, error: str | None = None) -> str:
    message = f'<p class="alert" role="alert">{html.escape(error)}</p>' if error else ""
    safe_request = html.escape(request_id, quote=True)
    client_name = html.escape(details["client_name"])
    redirect_uri = html.escape(details["redirect_uri"])
    scope = html.escape(details["scope"])
    audience = html.escape(details["audience"])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Authorize MCPRelay</title>
<style>
:root{{color-scheme:light dark;--background:#fff;--surface:#fff;--text:#111;--muted:#6b6b6b;--field:#f3f3f3;--border:#d7d7d7;--primary:#000;--primary-text:#fff;--danger:#b42318}}
*{{box-sizing:border-box}}
body{{min-height:100vh;margin:0;padding:2rem 1.25rem;display:grid;place-items:center;background:var(--background);color:var(--text);font:16px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{width:min(100%,26rem);text-align:center}}
.brand{{margin-bottom:2.5rem}}
.brand img{{display:block;width:min(100%,20rem);height:auto;margin:0 auto}}
h1{{margin:0;font-size:clamp(1.8rem,7vw,2.35rem);line-height:1.12;letter-spacing:-.04em}}
.intro{{margin:.75rem 0 2rem;color:var(--muted)}}
form{{display:grid;gap:.75rem}}
.sr-only{{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}}
input,button{{width:100%;min-height:3.35rem;border-radius:.75rem;font:inherit}}
input{{padding:0 1rem;border:1px solid var(--border);background:var(--field);color:var(--text);outline:none}}
input:focus{{border-color:var(--text);box-shadow:0 0 0 1px var(--text)}}
button{{padding:.75rem 1rem;border:1px solid transparent;font-weight:650;cursor:pointer}}
.primary{{background:var(--primary);color:var(--primary-text)}}
.primary:hover{{opacity:.82}}
.secondary{{border-color:var(--border);background:var(--surface);color:var(--text)}}
.secondary:hover{{background:var(--field)}}
.alert{{margin:0 0 1rem;padding:.75rem 1rem;border-radius:.65rem;background:#fee4e2;color:var(--danger);font-size:.9rem}}
.request-details{{margin:1.75rem 0 0;color:var(--muted);font-size:.75rem;line-height:1.4}}
.request-details div+div{{margin-top:.65rem}}
.request-details dt{{font-weight:650}}
.request-details dd{{margin:.1rem 0 0;overflow-wrap:anywhere}}
@media (prefers-color-scheme:dark){{:root{{--background:#111;--surface:#191919;--text:#f5f5f5;--muted:#a6a6a6;--field:#202020;--border:#3a3a3a;--primary:#f5f5f5;--primary-text:#111;--danger:#f97066}}.alert{{background:#3b1718}}}}
</style>
</head>
<body>
<main>
<header class="brand"><img src="/oauth/assets/vision.webp" alt="MCPRelay Vision"></header>
<h1>Authorize MCPRelay</h1>
<p class="intro"><strong>{client_name}</strong> requests access.</p>
{message}
<form method="post" action="/oauth/authorize">
<input type="hidden" name="request" value="{safe_request}">
<label><span class="sr-only">Access secret</span><input type="password" name="secret" required autofocus autocomplete="current-password" placeholder="Access secret"></label>
<button class="primary" type="submit" name="decision" value="authorize">Authorize</button>
<button class="secondary" type="submit" name="decision" value="deny" formnovalidate>Cancel</button>
</form>
<dl class="request-details">
<div><dt>Redirect</dt><dd>{redirect_uri}</dd></div>
<div><dt>Scope</dt><dd>{scope}</dd></div>
<div><dt>Audience</dt><dd>{audience}</dd></div>
</dl>
</main>
</body>
</html>"""
