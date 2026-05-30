from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

from .models import AGENT_STATUS_COMPLETED, AGENT_STATUS_FAILED, AGENT_STATUS_RUNNING
from .notifications import notify_agent_finished
from .store import AgentStore


def start_heartbeat(store: AgentStore, agent_id: str, interval_seconds: float = 10.0) -> threading.Event:
    stop = threading.Event()

    def beat():
        while not stop.wait(interval_seconds):
            store.update_status(agent_id, AGENT_STATUS_RUNNING, heartbeat=True)

    thread = threading.Thread(target=beat, daemon=True, name=f"agent-heartbeat-{agent_id}")
    thread.start()
    return stop


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--storage-dir", required=True)
    args = parser.parse_args(argv)

    store = AgentStore(args.db, args.storage_dir)
    record = store.get_agent(args.agent_id)
    if record is None:
        print(f"unknown agent_id: {args.agent_id}", file=sys.stderr)
        return 2

    store.update_status(args.agent_id, AGENT_STATUS_RUNNING, heartbeat=True, started=record.started_at is None)
    heartbeat_stop = start_heartbeat(store, args.agent_id)
    try:
        from .deepseek_runtime import (
            openinterpreter_defaults_for_provider,
            compose_deepseek_agent_prompt,
            run_openinterpreter_chat,
        )

        prompt = compose_deepseek_agent_prompt(record.prompt)
        default_model, default_api_base = openinterpreter_defaults_for_provider(record.provider)
        payload = run_openinterpreter_chat(
            prompt=prompt,
            model=record.model or default_model,
            api_base=record.api_base or default_api_base,
            api_key=None,
            auto_run=record.auto_run,
            provider=record.provider,
            llm_supports_functions=record.llm_supports_functions,
            context_window=record.context_window,
            max_tokens=record.max_tokens,
            cwd=Path(record.cwd or ".").expanduser().resolve(),
            stdout_target=sys.stdout,
            stderr_target=sys.stderr,
        )
        store.write_json(args.agent_id, "result.json", payload)
        store.update_status(args.agent_id, AGENT_STATUS_COMPLETED, exit_code=0, heartbeat=True, completed=True)
        completed_record = store.get_agent(args.agent_id)
        if completed_record is not None:
            try:
                notification = notify_agent_finished(completed_record, AGENT_STATUS_COMPLETED, payload)
            except Exception as notify_exc:
                notification = {"ok": False, "sent": False, "error": str(notify_exc)}
            store.append_event(args.agent_id, {"event": "notification", **notification})
        return 0
    except Exception as exc:
        result = {"ok": False, "error": str(exc), "error_type": exc.__class__.__name__}
        store.write_json(args.agent_id, "result.json", result)
        print(str(exc), file=sys.stderr)
        store.update_status(args.agent_id, AGENT_STATUS_FAILED, exit_code=1, error=str(exc), heartbeat=True, completed=True)
        failed_record = store.get_agent(args.agent_id)
        if failed_record is not None:
            try:
                notification = notify_agent_finished(failed_record, AGENT_STATUS_FAILED, result)
            except Exception as notify_exc:
                notification = {"ok": False, "sent": False, "error": str(notify_exc)}
            store.append_event(args.agent_id, {"event": "notification", **notification})
        return 1
    finally:
        heartbeat_stop.set()
        store.append_event(args.agent_id, {"event": "runner_finished", "finished_at": time.time()})


if __name__ == "__main__":
    raise SystemExit(main())
