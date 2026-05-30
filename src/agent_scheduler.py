#!/usr/bin/env python3
"""
Agent Scheduler CLI — Lance des agents scheduled via cron.

Usage:
    python3 src/agent_scheduler.py \
        --task-file config/tasks.json \
        --provider ollama \
        [--cwd /path] \
        [--purpose "Custom purpose"] \
        [--timeout 300]
"""

import argparse
import json
import logging
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
load_dotenv(BASE_DIR / 'config' / '.env', override=True)
(BASE_DIR / 'logs').mkdir(parents=True, exist_ok=True)

# Setup logging early
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)-8s %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(BASE_DIR / 'logs' / 'scheduler.log'),
    ]
)
logger = logging.getLogger(__name__)

# Import after env setup
from agent_manager import AgentManager, AgentSpec
from agent_manager.models import AGENT_STATUS_QUEUED, AGENT_STATUS_RUNNING, AgentRecord
from agent_metrics import get_metrics_instance
from scheduler_apple_notes import submit_apple_note_tasks


class SchedulerConfig:
    """Loads scheduler config from YAML."""
    
    def __init__(self, config_path: Path | None = None):
        if config_path is None:
            config_path = BASE_DIR / 'config' / 'scheduler.yaml'
        
        if not config_path.exists():
            logger.warning(f"Config not found: {config_path}, using defaults")
            self.config = {}
        else:
            with open(config_path) as f:
                self.config = yaml.safe_load(f) or {}
    
    @property
    def max_concurrent_local(self) -> int:
        return self.config.get('agents', {}).get('max_concurrent_local', 2)
    
    @property
    def defaults(self) -> dict[str, Any]:
        return self.config.get('scheduler', {}).get('defaults', {})

    @property
    def task_sources(self) -> list[dict[str, Any]]:
        return self.config.get('scheduler', {}).get('task_sources', [])

    @property
    def enabled_task_sources(self) -> list[dict[str, Any]]:
        return [source for source in self.task_sources if source.get('enabled', True)]
    
    @property
    def retry_enabled(self) -> bool:
        return self.config.get('retry', {}).get('enabled', True)
    
    @property
    def max_retry_attempts(self) -> int:
        return self.config.get('retry', {}).get('max_attempts', 3)
    
    @property
    def retry_backoff(self) -> list[int]:
        return self.config.get('retry', {}).get('backoff_seconds', [5, 15, 60])
    
    @property
    def retryable_statuses(self) -> set[str]:
        return set(self.config.get('retry', {}).get('retryable_statuses', []))
    
    @property
    def retry_patterns(self) -> list[str]:
        return self.config.get('retry', {}).get('retry_on_patterns', [])


def load_task_file(task_file: Path) -> dict[str, Any]:
    """Load task from JSON file."""
    if not task_file.exists():
        raise FileNotFoundError(f"Task file not found: {task_file}")
    
    with open(task_file) as f:
        data = json.load(f)
    
    logger.info(f"Loaded task from {task_file}: {data.get('name', 'unnamed')}")
    return data


def check_concurrent_limit(manager: AgentManager, limit: int) -> tuple[bool, int]:
    """
    Check if we can start a new agent.
    Returns (can_start, current_running).
    """
    agents = manager.list(status='running', include_completed=False)
    running_count = len(agents.get('agents', []))
    
    if running_count >= limit:
        logger.warning(
            f"Cannot start: {running_count}/{limit} agents already running. "
            f"Queuing instead."
        )
        return False, running_count
    
    return True, running_count


def compose_task_prompt(task_data: dict[str, Any]) -> str:
    """
    Compose the full prompt from task data.
    
    Expected structure:
    {
        "name": "Daily Report",
        "description": "Generate daily report",
        "prompt": "Please generate a daily status report..."
    }
    """
    prompt = task_data.get('prompt', '')
    description = task_data.get('description', '')
    
    if description and not prompt.startswith(description):
        prompt = f"{description}\n\n{prompt}"
    
    return prompt.strip()


def resolve_config_path(path_value: str | Path, base_dir: Path = BASE_DIR) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else base_dir / path


def build_task_spec(
    prompt: str,
    *,
    provider: str,
    model: str | None,
    purpose: str,
    cwd: Path | None,
    timeout: int | None,
    auto_run: bool,
    metadata: dict[str, Any],
) -> AgentSpec:
    if provider == 'ollama' and model and not model.startswith('ollama/'):
        model = f'ollama/{model}'
    return AgentSpec(
        prompt=prompt,
        provider=provider,
        model=model,
        purpose=purpose,
        cwd=str(cwd) if cwd else None,
        agent_timeout_seconds=timeout or 300,
        auto_run=auto_run,
        llm_supports_functions=provider != 'ollama',
        metadata=metadata,
    )


def submit_spec(manager: AgentManager, metrics, spec: AgentSpec, *, retry_of: str | None = None) -> dict[str, Any]:
    result = manager.submit(spec)
    agent_id = result['agent_id']
    logger.info(f"✓ Agent submitted: {agent_id}")
    logger.info(f"  Status: {result['status']}")
    logger.info(f"  Queue position: {result.get('position', 'N/A')}")
    logger.info(f"  View at: http://localhost:8761{result['status_url']}")
    if metrics:
        metrics.record(
            'agent_submitted',
            agent_id=agent_id,
            provider=spec.provider,
            purpose=spec.purpose,
            retry_of=retry_of,
            source=spec.metadata.get('source'),
        )
    return result


def submit_configured_sources(
    manager: AgentManager,
    metrics,
    config: SchedulerConfig,
    *,
    provider: str | None = None,
    model: str | None = None,
    cwd: Path | None = None,
    timeout: int | None = None,
    auto_run: bool | None = None,
) -> list[dict[str, Any]]:
    submitted = []
    defaults = config.defaults
    for source in config.enabled_task_sources:
        source_type = source.get('type')
        if source_type == 'json_file':
            task_file = resolve_config_path(source.get('path', 'config/tasks.json'))
            task_data = load_task_file(task_file)
            prompt = compose_task_prompt(task_data)
            if not prompt.strip():
                logger.warning(f"Skipping empty task file: {task_file}")
                continue
            spec = build_task_spec(
                prompt,
                provider=provider or source.get('provider') or defaults.get('provider', 'ollama'),
                model=model or source.get('model') or defaults.get('model'),
                purpose=task_data.get('name') or 'Scheduled task',
                cwd=cwd,
                timeout=timeout or source.get('agent_timeout_seconds') or defaults.get('agent_timeout_seconds', 300),
                auto_run=auto_run if auto_run is not None else bool(source.get('auto_run', defaults.get('auto_run', False))),
                metadata={
                    'scheduled': True,
                    'scheduled_at': datetime.now(UTC).isoformat(),
                    'source': str(task_file),
                    'task_name': task_data.get('name'),
                },
            )
            submitted.append(submit_spec(manager, metrics, spec))
        elif source_type == 'apple_notes':
            submitted.extend(
                submit_apple_note_tasks(
                    manager,
                    metrics,
                    config,
                    source,
                    base_dir=BASE_DIR,
                    provider=provider,
                    model=model,
                    cwd=cwd,
                    timeout=timeout,
                    auto_run=auto_run,
                )
            )
        else:
            logger.warning(f"Unknown task source type: {source_type}")
    return submitted


def retry_root_for(record: AgentRecord) -> str:
    """Return the stable root id for a retry chain."""
    return (
        record.metadata.get('retry_root')
        or record.parent_id
        or record.metadata.get('retry_of')
        or record.agent_id
    )


def is_retry_related(record: AgentRecord, root_id: str) -> bool:
    """Check whether a record belongs to a retry chain."""
    return (
        record.agent_id == root_id
        or record.parent_id == root_id
        or record.metadata.get('retry_root') == root_id
        or record.metadata.get('retry_of') == root_id
    )


def retry_attempt_count(root_id: str, records: list[AgentRecord]) -> int:
    """Count retry children already created for a root agent."""
    return sum(
        1
        for record in records
        if record.agent_id != root_id and is_retry_related(record, root_id)
    )


def has_active_retry(root_id: str, records: list[AgentRecord]) -> bool:
    """Avoid creating another retry while one retry child is queued/running."""
    return any(
        record.agent_id != root_id
        and is_retry_related(record, root_id)
        and record.status in {AGENT_STATUS_QUEUED, AGENT_STATUS_RUNNING}
        for record in records
    )


def retry_logs_match(logs: str, patterns: list[str]) -> bool:
    """Match retry patterns as regexes, with literal fallback for invalid regex."""
    if not patterns:
        return True
    for pattern in patterns:
        try:
            if re.search(pattern, logs, re.IGNORECASE):
                return True
        except re.error:
            if pattern.lower() in logs.lower():
                return True
    return False


def retry_backoff_seconds(config: SchedulerConfig, retry_count: int) -> int:
    """Return the backoff delay before creating the next retry."""
    backoff = config.retry_backoff
    if not backoff:
        return 0
    index = min(max(retry_count, 0), len(backoff) - 1)
    return int(backoff[index])


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def retry_ready_at(record: AgentRecord, config: SchedulerConfig, retry_count: int) -> datetime | None:
    """Compute when a retry may be created for a failed record."""
    base = parse_timestamp(record.completed_at) or parse_timestamp(record.updated_at)
    if base is None:
        return None
    return base + timedelta(seconds=retry_backoff_seconds(config, retry_count))


def should_retry_agent(
    agent_id: str,
    manager: AgentManager,
    config: SchedulerConfig,
    *,
    now: datetime | None = None,
) -> bool:
    """Check if agent should be retried now."""
    if not config.retry_enabled:
        return False
    
    try:
        record = manager.store.get_agent(agent_id)
        if record is None:
            return False
        
        # Check status is retryable
        if record.status not in config.retryable_statuses:
            return False
        
        root_id = retry_root_for(record)
        records = manager.store.list_agents(
            status=None,
            limit=500,
            include_completed=True
        )
        retry_count = retry_attempt_count(root_id, records)
        
        if retry_count >= config.max_retry_attempts:
            logger.warning(f"Agent {agent_id} retry limit reached ({retry_count}/{config.max_retry_attempts})")
            return False

        if has_active_retry(root_id, records):
            logger.info(f"Agent {agent_id} already has an active retry in chain {root_id}")
            return False

        now = now or datetime.now(UTC)
        ready_at = retry_ready_at(record, config, retry_count)
        if ready_at and now < ready_at:
            logger.info(f"Agent {agent_id} retry delayed until {ready_at.isoformat()}")
            return False
        
        # Check error patterns
        logs = manager.store.tail_log(agent_id, stream='stderr', tail=100)
        if not logs:
            logs = record.error or ''
        return retry_logs_match(logs, config.retry_patterns)
        
    except Exception as e:
        logger.error(f"Error checking retry status: {e}")
        return False


def submit_retry_agent(
    agent_id: str,
    manager: AgentManager,
    config: SchedulerConfig,
    metrics=None,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Submit a retry child if policy allows it."""
    record = manager.store.get_agent(agent_id)
    if record is None or not should_retry_agent(agent_id, manager, config, now=now):
        return None

    records = manager.store.list_agents(status=None, limit=500, include_completed=True)
    root_id = retry_root_for(record)
    retry_count = retry_attempt_count(root_id, records)
    retry_attempt = retry_count + 1
    retry_now = now or datetime.now(UTC)
    metadata = {
        **record.metadata,
        'retry_of': agent_id,
        'retry_root': root_id,
        'retry_attempt': retry_attempt,
        'retry_scheduled_at': retry_now.isoformat(),
    }
    spec = AgentSpec(
        prompt=record.prompt,
        provider=record.provider,
        purpose=record.purpose,
        cwd=record.cwd,
        model=record.model,
        api_base=record.api_base,
        auto_run=record.auto_run,
        llm_supports_functions=record.llm_supports_functions,
        context_window=record.context_window,
        max_tokens=record.max_tokens,
        wait_timeout_seconds=record.wait_timeout_seconds,
        agent_timeout_seconds=record.agent_timeout_seconds,
        conversation_id=record.conversation_id,
        chatgpt_url=record.chatgpt_url,
        metadata=metadata,
    )
    result = manager.submit(spec, parent_id=agent_id)
    if metrics:
        metrics.record(
            'retry_attempt',
            agent_id=result['agent_id'],
            retry_of=agent_id,
            retry_root=root_id,
            retry_attempt=retry_attempt,
        )
    logger.info(
        f"Retry submitted for {agent_id}: {result['agent_id']} "
        f"({retry_attempt}/{config.max_retry_attempts})"
    )
    return result


def process_retryable_agents(
    manager: AgentManager,
    config: SchedulerConfig,
    metrics=None,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Scan retryable statuses and submit eligible retry children."""
    if not config.retry_enabled:
        return []
    submitted = []
    for status in config.retryable_statuses:
        for record in manager.store.list_agents(status=status, limit=500, include_completed=True):
            result = submit_retry_agent(record.agent_id, manager, config, metrics=metrics, now=now)
            if result:
                submitted.append(result)
    return submitted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Schedule an agent to run via cron or CLI"
    )
    parser.add_argument(
        '--task-file',
        type=Path,
        default=None,
        help='Path to task JSON file (e.g., config/tasks.json)'
    )
    parser.add_argument(
        '--task-source',
        choices=['configured', 'json_file', 'apple_notes'],
        default=None,
        help='Task source to scan. configured reads enabled sources from config/scheduler.yaml'
    )
    parser.add_argument(
        '--task-name',
        type=str,
        default=None,
        help='Task name for dynamic tasks (e.g., from Apple Notes)'
    )
    parser.add_argument(
        '--provider',
        type=str,
        choices=['ollama', 'deepseek'],
        default='ollama',
        help='LLM provider (default: ollama)'
    )
    parser.add_argument(
        '--model',
        type=str,
        default=None,
        help='Model override (default: qwen3.5:35b-a3b-coding-nvfp4 for ollama)'
    )
    parser.add_argument(
        '--cwd',
        type=Path,
        default=None,
        help='Working directory for agent'
    )
    parser.add_argument(
        '--purpose',
        type=str,
        default=None,
        help='Agent purpose (default: from task)'
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=None,
        help='Agent timeout in seconds (default: 300)'
    )
    parser.add_argument(
        '--prompt',
        type=str,
        default=None,
        help='Direct prompt (overrides task file)'
    )
    parser.add_argument(
        '--auto-run',
        action='store_true',
        help='Auto-run code without confirmation'
    )
    parser.add_argument(
        '--retry-of',
        type=str,
        default=None,
        help='Agent ID to retry (internal use)'
    )
    parser.add_argument(
        '--retry-agent',
        type=str,
        default=None,
        help='Retry a specific failed/timeout_soft agent if policy allows it'
    )
    parser.add_argument(
        '--process-retries-only',
        action='store_true',
        help='Process eligible retries and exit without submitting a new task'
    )
    
    args = parser.parse_args(argv)
    
    try:
        # 1. Load config
        config = SchedulerConfig()
        logger.info(
            f"Scheduler config loaded. "
            f"Max concurrent: {config.max_concurrent_local}"
        )
        
        # 2. Initialize metrics
        metrics = get_metrics_instance(BASE_DIR, config.config)
        
        # 3. Initialize AgentManager
        storage_dir = BASE_DIR / 'data' / 'agents'
        manager = AgentManager(
            storage_dir=storage_dir,
            max_running_agents=config.max_concurrent_local,
        )
        logger.info(f"AgentManager initialized at {storage_dir}")

        # 4. Process retry queue before scheduling new work.
        if args.retry_agent:
            result = submit_retry_agent(args.retry_agent, manager, config, metrics=metrics)
            if not result:
                logger.info(f"No retry submitted for {args.retry_agent}")
                return 0
            return 0

        retry_results = process_retryable_agents(manager, config, metrics=metrics)
        if retry_results:
            logger.info(f"Processed {len(retry_results)} retry attempt(s)")
        if args.process_retries_only:
            return 0
        
        # 5. Check concurrent limit
        can_start, running = check_concurrent_limit(manager, config.max_concurrent_local)
        
        # 6. Load task data
        task_data = {}
        if args.task_source == 'configured':
            submit_configured_sources(
                manager,
                metrics,
                config,
                provider=args.provider,
                model=args.model,
                cwd=args.cwd,
                timeout=args.timeout,
                auto_run=args.auto_run,
            )
            return 0
        if args.task_source == 'apple_notes':
            sources = [
                source for source in config.task_sources
                if source.get('type') == 'apple_notes'
            ]
            source_config = sources[0] if sources else {'type': 'apple_notes', 'hashtag': '#iatasks'}
            submit_apple_note_tasks(
                manager,
                metrics,
                config,
                source_config,
                base_dir=BASE_DIR,
                provider=args.provider,
                model=args.model,
                cwd=args.cwd,
                timeout=args.timeout,
                auto_run=args.auto_run,
            )
            return 0
        if args.task_source == 'json_file' and not args.task_file:
            sources = [
                source for source in config.task_sources
                if source.get('type') == 'json_file'
            ]
            if sources:
                args.task_file = resolve_config_path(sources[0].get('path', 'config/tasks.json'))

        if args.prompt:
            prompt = args.prompt
            task_data['name'] = 'Direct prompt'
        elif args.task_file:
            task_data = load_task_file(args.task_file)
            prompt = compose_task_prompt(task_data)
        elif args.task_name:
            logger.error(f"Task name provided: {args.task_name} (Apple Notes not yet supported)")
            return 1
        else:
            logger.error("Must provide either --task-file, --prompt, or --task-name")
            return 1
        
        if not prompt.strip():
            logger.error("Task prompt is empty")
            return 1
        
        # 7. Build AgentSpec
        spec = AgentSpec(
            prompt=prompt,
            provider=args.provider,
            model=args.model,
            purpose=args.purpose or task_data.get('name') or 'Scheduled task',
            cwd=str(args.cwd) if args.cwd else None,
            agent_timeout_seconds=args.timeout or 300,
            auto_run=args.auto_run,
            metadata={
                'scheduled': True,
                'scheduled_at': datetime.now(UTC).isoformat(),
                'source': str(args.task_file) if args.task_file else 'direct_prompt',
                'task_name': task_data.get('name'),
                'retry_of': args.retry_of,
            }
        )
        
        logger.info(
            f"Creating agent: provider={args.provider}, "
            f"timeout={spec.agent_timeout_seconds}s"
        )
        
        # 8. Submit agent and record metrics
        submit_spec(manager, metrics, spec, retry_of=args.retry_of)
        
        return 0
        
    except Exception as e:
        logger.error(f"✗ Failed to schedule agent: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
