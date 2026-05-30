from __future__ import annotations

import html
import json as _json

from fastapi import FastAPI, Form, Query
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


VIEWPORT_META = '<meta name="viewport" content="width=device-width, initial-scale=1">'


BASE_STYLE = """
:root {
  color-scheme: dark;
  --bg0: #06111f;
  --bg1: #0b2143;
  --bg2: #103b68;
  --panel: rgba(246, 250, 255, 0.96);
  --panel-soft: rgba(231, 241, 255, 0.9);
  --ink: #0a1628;
  --muted: #5c6f89;
  --line: rgba(31, 83, 128, 0.18);
  --cyan: #00d4ff;
  --blue: #2f80ff;
  --green: #1fd18b;
  --red: #ff5b7c;
  --amber: #ffbd45;
}
* { box-sizing: border-box; }
html {
  -webkit-text-size-adjust: 100%;
}
body {
  min-height: 100vh;
  margin: 0;
  overflow-x: hidden;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: #eef7ff;
  background:
    radial-gradient(circle at 20% 10%, rgba(0, 212, 255, 0.18), transparent 28%),
    linear-gradient(135deg, var(--bg0) 0%, var(--bg1) 48%, var(--bg2) 100%);
}
a { color: inherit; }
.shell {
  width: min(1180px, calc(100vw - 40px));
  margin: 0 auto;
  padding: 30px 0 42px;
}
.topbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 22px;
}
.eyebrow {
  color: var(--cyan);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
h1 {
  margin: 4px 0 0;
  font-size: clamp(32px, 5vw, 58px);
  line-height: 0.95;
  letter-spacing: 0;
  overflow-wrap: anywhere;
}
h2 {
  margin: 0 0 14px;
  color: var(--ink);
  font-size: 20px;
}
.nav-link {
  display: inline-flex;
  align-items: center;
  min-height: 38px;
  padding: 0 14px;
  border: 1px solid rgba(0, 212, 255, 0.35);
  border-radius: 8px;
  color: #e7f8ff;
  text-decoration: none;
  background: rgba(6, 17, 31, 0.34);
}
.stats {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  gap: 12px;
  margin: 0 0 18px;
}
.stat {
  border: 1px solid rgba(151, 208, 255, 0.24);
  border-radius: 8px;
  padding: 13px 14px;
  background: rgba(6, 17, 31, 0.48);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.08);
}
.stat span {
  display: block;
  color: #9fc0dc;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}
.stat strong {
  display: block;
  margin-top: 5px;
  font-size: 26px;
  line-height: 1;
}
.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}
.agent-card,
.panel {
  position: relative;
  border: 1px solid rgba(214, 232, 255, 0.78);
  border-radius: 8px;
  background: var(--panel);
  color: var(--ink);
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.28), inset 0 1px 0 rgba(255,255,255,0.9);
}
.agent-card {
  min-height: 190px;
  padding: 16px;
  overflow: hidden;
  min-width: 0;
}
.agent-card::before,
.panel::before {
  content: "";
  position: absolute;
  inset: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--cyan), var(--blue), var(--green));
}
.agent-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}
.agent-id {
  color: #082044;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 15px;
  font-weight: 800;
  overflow-wrap: anywhere;
}
.badge {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 5px 9px;
  color: white;
  background: var(--blue);
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
}
.badge.running { background: var(--green); color: #03291a; }
.badge.failed, .badge.cancelled { background: var(--red); }
.badge.queued { background: var(--amber); color: #2d1a00; }
.meta {
  display: grid;
  gap: 8px;
  margin: 16px 0;
  color: var(--muted);
  font-size: 13px;
}
.meta-row {
  display: grid;
  grid-template-columns: 74px 1fr;
  gap: 10px;
  min-width: 0;
}
.meta-row span:first-child {
  color: #37516f;
  font-weight: 800;
  text-transform: uppercase;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  overflow-wrap: anywhere;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: auto;
}
.btn,
button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 36px;
  border: 0;
  border-radius: 8px;
  padding: 0 13px;
  color: white;
  background: linear-gradient(135deg, #0c59d8, #00a9d8);
  font-weight: 800;
  text-decoration: none;
  cursor: pointer;
  text-align: center;
  white-space: nowrap;
}
.btn.secondary {
  color: #0d2443;
  background: #e7f1ff;
  border: 1px solid #c6dcf7;
}
.btn.danger,
button.danger {
  background: linear-gradient(135deg, #b51f4d, #ff5b7c);
}
.panel {
  padding: 18px;
  margin-bottom: 16px;
  overflow: hidden;
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 10px;
}
.detail-item {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 11px 12px;
  background: var(--panel-soft);
  min-width: 0;
}
.detail-item span {
  display: block;
  color: #49647f;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}
.detail-item strong {
  display: block;
  margin-top: 5px;
  overflow-wrap: anywhere;
}
form {
  display: grid;
  gap: 10px;
}
label {
  color: #233b59;
  font-weight: 800;
}
input,
textarea {
  width: 100%;
  border: 1px solid #b9cde5;
  border-radius: 8px;
  padding: 10px 11px;
  color: var(--ink);
  background: white;
  font: inherit;
  min-width: 0;
}
input[type="checkbox"] {
  width: auto;
  margin: 0 8px 0 0;
  accent-color: var(--cyan);
}
textarea {
  min-height: 180px;
  resize: vertical;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
pre {
  max-height: 320px;
  margin: 0;
  overflow: auto;
  border: 1px solid #c6dcf7;
  border-radius: 8px;
  padding: 12px;
  color: #d9f9ff;
  background: #06111f;
  font-size: 13px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.empty {
  padding: 24px;
  border: 1px dashed rgba(168, 214, 255, 0.4);
  border-radius: 8px;
  color: #b9d7ef;
  background: rgba(6, 17, 31, 0.34);
}
.log-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0 0 14px;
}
.log-tabs .active {
  color: white;
  background: linear-gradient(135deg, #0c59d8, #00a9d8);
  border-color: transparent;
}
.log-empty {
  min-height: 180px;
  display: grid;
  place-items: center;
  border: 1px dashed #abc6e4;
  border-radius: 8px;
  color: #506987;
  background: rgba(255, 255, 255, 0.6);
  font-weight: 800;
}
@media (max-width: 760px) {
  .shell { width: min(1180px, calc(100vw - 24px)); padding: 18px 0 28px; }
  .topbar { align-items: stretch; flex-direction: column; gap: 12px; }
  .nav-link { justify-content: center; width: 100%; }
  .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .stat { padding: 11px 12px; }
  .stat strong { font-size: 22px; }
  .agent-grid { grid-template-columns: 1fr; }
  .agent-head { align-items: stretch; flex-direction: column; gap: 8px; }
  .badge { align-self: flex-start; }
  .meta-row { grid-template-columns: 1fr; gap: 2px; }
  .actions { display: grid; grid-template-columns: 1fr 1fr; }
  .btn, button { width: 100%; min-width: 0; white-space: normal; }
  .detail-grid { grid-template-columns: 1fr; }
  .panel { padding: 14px; }
  textarea { min-height: 220px; }
  pre { max-height: 260px; font-size: 12px; }
}
@media (max-width: 420px) {
  .shell { width: calc(100vw - 16px); padding-top: 12px; }
  h1 { font-size: 30px; line-height: 1; }
  .stats { grid-template-columns: 1fr; gap: 8px; }
  .actions, .log-tabs { display: grid; grid-template-columns: 1fr; }
  .agent-card, .panel { padding: 12px; }
}
"""


def status_class(status: str | None) -> str:
    safe = (status or "unknown").lower().replace("_", "-")
    return "".join(ch for ch in safe if ch.isalnum() or ch == "-")


def render_result_text(result) -> str:
    return _json.dumps(result, indent=2, ensure_ascii=False) if result is not None else ""


def render_stats(payload: dict) -> str:
    counts = payload["counts"]
    return f"""
      <div class="stat"><span>Running</span><strong>{esc(counts.get('running', 0))} / {esc(payload['max_running_agents'])}</strong></div>
      <div class="stat"><span>Queued</span><strong>{esc(counts.get('queued', 0))}</strong></div>
      <div class="stat"><span>Failed</span><strong>{esc(counts.get('failed', 0))}</strong></div>
      <div class="stat"><span>Stale</span><strong>{esc(counts.get('stale', 0))}</strong></div>
      <div class="stat"><span>Completed</span><strong>{esc(counts.get('completed', 0))}</strong></div>
    """


def render_agent_cards(payload: dict) -> str:
    rows = []
    for agent in payload["agents"]:
        agent_id = agent["agent_id"]
        status_value = esc(agent.get("status"))
        rows.append(
            "<article class='agent-card'>"
            "<div class='agent-head'>"
            f"<a class='agent-id' href='./{esc(agent_id)}'>{esc(agent_id)}</a>"
            f"<span class='badge {esc(status_class(agent.get('status')))}'>{status_value}</span>"
            "</div>"
            "<div class='meta'>"
            f"<div class='meta-row'><span>Purpose</span><strong>{esc(agent.get('purpose') or 'No purpose')}</strong></div>"
            f"<div class='meta-row'><span>CWD</span><strong class='mono'>{esc(agent.get('cwd'))}</strong></div>"
            f"<div class='meta-row'><span>Timeout</span><strong>{_fmt_timeout_vs_elapsed(agent) or esc(agent.get('agent_timeout_seconds') or '∞') + 's'}</strong></div>"
            f"<div class='meta-row'><span>Updated</span><strong>{esc(agent.get('updated_at'))}</strong></div>"
            "</div>"
            "<div class='actions'>"
            f"<a class='btn' href='./{esc(agent_id)}'>View</a>"
            f"<a class='btn secondary' href='./{esc(agent_id)}/logs?stream=stdout'>Logs</a>"
            "</div>"
            "</article>"
        )
    return "".join(rows) if rows else "<div class='empty'>No agents found.</div>"


def _fmt_elapsed(agent: dict, now_ts: float | None = None) -> str:
    """Formats the elapsed time since started_at as 'XmYs' or '' if not started."""
    started = agent.get("started_at")
    if not started:
        return ""
    try:
        from datetime import UTC, datetime
        started_dt = datetime.fromisoformat(started)
        now = datetime.fromtimestamp(now_ts, tz=UTC) if now_ts else datetime.now(UTC)
        elapsed = int((now - started_dt).total_seconds())
        mins, secs = divmod(elapsed, 60)
        return f"{mins}m{secs:02d}s"
    except Exception:
        return ""


def _fmt_timeout_vs_elapsed(agent: dict) -> str:
    """Returns a human-readable string like '3m12s / 5m (requested)' or '3m12s / ∞'."""
    elapsed = _fmt_elapsed(agent)
    if not elapsed:
        return ""
    timeout = agent.get("agent_timeout_seconds")
    if timeout:
        tmins, tsecs = divmod(int(timeout), 60)
        timeout_str = f"{tmins}m{tsecs:02d}s"
        return f"{elapsed} / {timeout_str} (requested)"
    return f"{elapsed} / ∞"


def create_agents_app(manager):
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    async def list_agents(
        status: str | None = None,
        limit: int = Query(50, ge=1, le=500),
        partial: bool = False,
    ):
        payload = manager.list(status=status, limit=limit)
        stats = render_stats(payload)
        cards = render_agent_cards(payload)
        if partial:
            return HTMLResponse(
                f"<template id='stats'>{stats}</template><template id='cards'>{cards}</template>"
            )
        body = f"""
        <html><head><title>Agents</title>{VIEWPORT_META}<style>{BASE_STYLE}</style></head><body>
        <main class="shell">
        <div class="topbar">
          <div>
            <div class="eyebrow">DeepSeek Operations</div>
            <h1>Agents</h1>
          </div>
        </div>
        <section class="stats" id="agent-stats">{stats}</section>
        <section class="agent-grid" id="agent-grid">{cards}</section>
        </main>
        <script>
        async function refreshAgents() {{
          try {{
            const response = await fetch('./?partial=1', {{ cache: 'no-store' }});
            if (!response.ok) return;
            const text = await response.text();
            const doc = new DOMParser().parseFromString(text, 'text/html');
            const stats = doc.querySelector('#stats');
            const cards = doc.querySelector('#cards');
            if (stats) document.querySelector('#agent-stats').innerHTML = stats.innerHTML;
            if (cards) document.querySelector('#agent-grid').innerHTML = cards.innerHTML;
          }} catch (_err) {{}}
        }}
        setInterval(refreshAgents, 3000);
        </script>
        </body></html>
        """
        return HTMLResponse(body)

    @app.get("/{agent_id}", response_class=HTMLResponse)
    async def view_agent(agent_id: str):
        payload = manager.get(agent_id)
        agent = payload["agent"]
        result = payload.get("result")
        can_edit = agent.get("status") != "running"
        controls = ""
        if can_edit:
            controls = f"""
            <section class="panel"><h2>Edit input</h2>
            <form method="post" action="./{esc(agent_id)}/update">
              <label>Purpose<input name="purpose" value="{esc(agent.get('purpose'))}"></label>
              <label>Provider<input name="provider" value="{esc(agent.get('provider') or 'deepseek')}"></label>
              <label>CWD<input name="cwd" value="{esc(agent.get('cwd'))}"></label>
              <label>Timeout (seconds, empty = default/∞)<input name="agent_timeout_seconds" value="{esc(agent.get('agent_timeout_seconds') or '')}"></label>
              <label>Prompt</label>
              <textarea name="prompt">{esc(agent.get('prompt'))}</textarea>
              <button type="submit">Save input</button>
            </form>
            <form method="post" action="./{esc(agent_id)}/retry"><button type="submit">Retry as new</button></form></section>
            """
        cancel = f"""
        <form method="post" action="./{esc(agent_id)}/cancel">
          <label><input type="checkbox" name="force" value="true"> Force</label>
          <button class="danger" type="submit">Cancel</button>
        </form>
        """
        is_running = agent.get("status") == "running" or agent.get("status") == "queued"
        body = f"""
        <html><head><title>{esc(agent_id)}</title>{VIEWPORT_META}<style>{BASE_STYLE}</style></head><body>
        <main class="shell">
        <div class="topbar">
          <div>
            <div class="eyebrow">Agent Detail</div>
            <h1>{esc(agent_id)}</h1>
          </div>
          <a class="nav-link" href="./">Agents</a>
        </div>
        <section class="panel">
          <div class="detail-grid">
            <div class="detail-item"><span>Status</span><strong><span class="badge {esc(status_class(agent.get('status')))}" id="live-status">{esc(agent.get('status'))}</span></strong></div>
            <div class="detail-item"><span>Purpose</span><strong>{esc(agent.get('purpose'))}</strong></div>
            <div class="detail-item"><span>Provider</span><strong>{esc(agent.get('provider') or 'deepseek')}</strong></div>
            <div class="detail-item"><span>CWD</span><strong class="mono">{esc(agent.get('cwd'))}</strong></div>
            <div class="detail-item"><span>Model</span><strong>{esc(agent.get('model'))}</strong></div>
            <div class="detail-item"><span>Max tokens</span><strong>{esc(agent.get('max_tokens'))}</strong></div>
            <div class="detail-item"><span>Timeout</span><strong>{esc(agent.get('agent_timeout_seconds') or '∞')}s</strong></div>
            <div class="detail-item"><span>Elapsed</span><strong id="live-elapsed">{esc(_fmt_elapsed(agent)) or '—'}</strong></div>
          </div>
        </section>
        <section class="panel"><h2>Control</h2>{cancel}</section>
        {controls}
        <section class="panel"><h2>stdout</h2><pre id="live-stdout">{esc(manager.logs(agent_id, "stdout", 100).get("content"))}</pre></section>
        <section class="panel"><h2>stderr</h2><pre id="live-stderr">{esc(manager.logs(agent_id, "stderr", 100).get("content"))}</pre></section>
        <section class="panel"><h2>result</h2><pre id="live-result">{esc(render_result_text(result))}</pre></section>
        <section class="panel"><h2>events</h2><pre id="live-events">{esc(manager.logs(agent_id, "events", 100).get("content"))}</pre></section>
        </main>
        <script>
        const AGENT_ID = {esc(_json.dumps(agent_id))};
        let POLLING = true;

        async function refreshAgent() {{
          if (!POLLING) return;
          try {{
            const resp = await fetch('./' + encodeURIComponent(AGENT_ID) + '/live', {{ cache: 'no-store' }});
            if (!resp.ok) {{ POLLING = false; return; }}
            const data = await resp.json();

            // status badge
            const statusEl = document.getElementById('live-status');
            if (statusEl) {{
              statusEl.textContent = data.status;
              statusEl.className = 'badge ' + data.status_class;
            }}

            // elapsed
            const elapsedEl = document.getElementById('live-elapsed');
            if (elapsedEl) elapsedEl.textContent = data.elapsed || '—';

            // logs
            const streams = ['stdout', 'stderr', 'events'];
            for (const s of streams) {{
              const el = document.getElementById('live-' + s);
              if (el) {{
                const old = el.textContent;
                el.textContent = data.logs[s] || '';
                if (el.textContent !== old) {{
                  el.scrollTop = el.scrollHeight;
                }}
              }}
            }}

            // result (only updates if changed)
            const resultEl = document.getElementById('live-result');
            if (resultEl && data.result !== undefined) {{
              resultEl.textContent = data.result;
            }}

            // stop polling if terminal
            if (!data.is_running) {{
              POLLING = false;
            }}
          }} catch (_err) {{}}
        }}

        setInterval(refreshAgent, 2000);
        refreshAgent();
        </script>
        </body></html>
        """
        return HTMLResponse(body)

    @app.get("/{agent_id}/live")
    async def live_agent(agent_id: str):
        try:
            payload = manager.get(agent_id)
        except KeyError:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "unknown agent", "agent_id": agent_id}, status_code=404)
        agent = payload["agent"]
        result = payload.get("result")
        elapsed = _fmt_elapsed(agent)
        status = agent.get("status", "")
        is_running = status in ("running", "queued")
        return {
            "status": status,
            "status_class": status_class(status),
            "elapsed": elapsed or "",
            "is_running": is_running,
            "result": render_result_text(result),
            "logs": {
                "stdout": manager.logs(agent_id, "stdout", 100).get("content", ""),
                "stderr": manager.logs(agent_id, "stderr", 100).get("content", ""),
                "events": manager.logs(agent_id, "events", 100).get("content", ""),
            },
        }

    @app.get("/{agent_id}/logs", response_class=PlainTextResponse)
    async def view_logs(
        agent_id: str,
        stream: str = "stdout",
        tail: int = Query(500, ge=1, le=2000),
        raw: bool = False,
    ):
        payload = manager.logs(agent_id, stream=stream, tail=tail)
        content = payload["content"]
        if raw:
            return PlainTextResponse(content)
        tabs = []
        for item in ("stdout", "stderr", "events"):
            active = " active" if item == stream else ""
            tabs.append(
                f"<a class='btn secondary{active}' href='./logs?stream={esc(item)}&tail={esc(tail)}'>{esc(item)}</a>"
            )
        log_body = f"<pre>{esc(content)}</pre>" if content else (
            f"<div class='log-empty'>No {esc(stream)} lines yet for this agent.</div>"
        )
        body = f"""
        <html><head><title>{esc(agent_id)} {esc(stream)} logs</title>{VIEWPORT_META}<style>{BASE_STYLE}</style></head><body>
        <main class="shell">
        <div class="topbar">
          <div>
            <div class="eyebrow">Agent Logs</div>
            <h1>{esc(agent_id)}</h1>
          </div>
          <a class="nav-link" href="../{esc(agent_id)}">Agent</a>
        </div>
        <section class="panel">
          <h2>{esc(stream)} logs</h2>
          <div class="log-tabs">{''.join(tabs)}</div>
          {log_body}
        </section>
        </main>
        </body></html>
        """
        return HTMLResponse(body)

    @app.post("/{agent_id}/cancel")
    async def cancel_agent(agent_id: str, force: bool = Form(False)):
        manager.cancel(agent_id, force=force)
        return RedirectResponse(f"../{agent_id}", status_code=303)

    @app.post("/{agent_id}/update")
    async def update_agent(
        agent_id: str,
        prompt: str = Form(None),
        purpose: str = Form(None),
        cwd: str = Form(None),
        provider: str = Form(None),
        agent_timeout_seconds: str = Form(None),
    ):
        kwargs: dict[str, Any] = {"prompt": prompt, "purpose": purpose, "provider": provider, "cwd": cwd}
        if agent_timeout_seconds is not None and agent_timeout_seconds.strip():
            kwargs["agent_timeout_seconds"] = int(agent_timeout_seconds)
        elif agent_timeout_seconds is not None:
            kwargs["agent_timeout_seconds"] = None
        manager.update(agent_id, **kwargs)
        return RedirectResponse(f"../{agent_id}", status_code=303)

    @app.post("/{agent_id}/retry")
    async def retry_agent(agent_id: str):
        result = manager.retry(agent_id)
        return RedirectResponse(f"../{result['agent_id']}", status_code=303)

    return app
