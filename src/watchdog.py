#!/usr/bin/env python3
"""
Agent Watchdog — Détecte et tue les agents qui loopent.

Lance périodiquement (via cron: */5 * * * *):
    python3 src/watchdog.py

Détecte les patterns de boucle infinies avec scoring.
Gère aussi la queue et les limites.
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

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)-8s %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(BASE_DIR / 'logs' / 'watchdog.log'),
    ]
)
logger = logging.getLogger(__name__)

from agent_manager import AgentManager
from agent_manager.models import (
    AGENT_STATUS_RUNNING,
    AGENT_STATUS_CANCELLED,
    AGENT_STATUS_TIMEOUT_HARD,
    TERMINAL_AGENT_STATUSES,
)
from agent_metrics import get_metrics_instance


class WatchdogConfig:
    """Load and parse watchdog config from scheduler.yaml."""
    
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
    def enabled(self) -> bool:
        return self.config.get('watchdog', {}).get('enabled', True)
    
    @property
    def check_interval(self) -> int:
        return self.config.get('watchdog', {}).get('check_interval_seconds', 300)
    
    @property
    def hard_timeout(self) -> int:
        return self.config.get('watchdog', {}).get('hard_timeout_seconds', 3600)
    
    @property
    def loop_patterns(self) -> list[dict[str, str]]:
        return self.config.get('watchdog', {}).get('patterns', [])
    
    @property
    def duplication_threshold(self) -> float:
        return (
            self.config.get('watchdog', {})
            .get('loop_detection', {})
            .get('duplication_threshold', 0.60)
        )
    
    @property
    def error_threshold(self) -> float:
        return (
            self.config.get('watchdog', {})
            .get('loop_detection', {})
            .get('error_threshold', 0.40)
        )
    
    @property
    def progress_similarity(self) -> float:
        return (
            self.config.get('watchdog', {})
            .get('loop_detection', {})
            .get('progress_similarity', 0.70)
        )


class LoopDetector:
    """Détecte les boucles infinies avec scoring intelligent."""
    
    def __init__(self, config: WatchdogConfig):
        self.config = config
        self.compiled_patterns = [
            (re.compile(p['pattern'], re.IGNORECASE), p)
            for p in config.loop_patterns
        ]
    
    def detect(self, logs: str, agent_id: str) -> tuple[bool, str | None]:
        """
        Analyse les logs pour détecter une boucle.
        Retourne (is_loop, reason).
        """
        if not logs or not logs.strip():
            return False, None
        
        lines = logs.split('\n')[-200:]  # Derniers 200 lignes
        recent = '\n'.join(lines)
        
        # Check 1: Patterns spécifiques (critiques)
        for pattern_re, pattern_info in self.compiled_patterns:
            try:
                if pattern_re.search(recent):
                    reason = f"Pattern: {pattern_info.get('reason', 'Unknown pattern')}"
                    severity = pattern_info.get('severity', 'medium')
                    logger.warning(
                        f"[{agent_id}] Loop detected ({severity}): {reason}"
                    )
                    return True, reason
            except re.error as e:
                logger.warning(f"Invalid pattern: {e}")
                continue
        
        # Check 2: Duplication de lignes
        unique_lines = len(set(lines))
        dup_ratio = 1 - (unique_lines / len(lines)) if lines else 0
        
        if dup_ratio > self.config.duplication_threshold:
            reason = f"High output duplication: {dup_ratio:.0%}"
            logger.warning(f"[{agent_id}] Loop detected: {reason}")
            return True, reason
        
        # Check 3: Spam d'erreurs
        error_lines = [
            l for l in lines
            if any(x in l.lower() for x in ['error', 'exception', 'traceback'])
        ]
        error_ratio = len(error_lines) / len(lines) if lines else 0
        
        if error_ratio > self.config.error_threshold:
            reason = f"Error spam: {error_ratio:.0%}"
            logger.warning(f"[{agent_id}] Loop detected: {reason}")
            return True, reason
        
        # Check 4: Pas de progrès (même logs)
        if len(lines) > 50:
            first_half_set = set(lines[:25])
            second_half_set = set(lines[-25:])
            
            overlap = len(first_half_set & second_half_set)
            max_set = max(len(first_half_set), len(second_half_set))
            
            similarity = overlap / max_set if max_set > 0 else 0
            
            if similarity > self.config.progress_similarity:
                reason = f"No progress: {similarity:.0%} overlap between start and end"
                logger.warning(f"[{agent_id}] Loop detected: {reason}")
                return True, reason
        
        return False, None


def check_agent_health(
    manager: AgentManager,
    agent_id: str,
    detector: LoopDetector,
    hard_timeout: int,
) -> tuple[bool, str | None]:
    """
    Vérifie la santé d'un agent.
    Retourne (should_kill, kill_reason).
    """
    try:
        record = manager.store.get_agent(agent_id)
        if record is None:
            logger.debug(f"Agent {agent_id} not found, skipping")
            return False, None
        
        if record.status != AGENT_STATUS_RUNNING:
            logger.debug(f"Agent {agent_id} not running (status: {record.status})")
            return False, None
        
        # 1. Check hard timeout
        if record.started_at:
            started = datetime.fromisoformat(record.started_at)
            now = datetime.now(UTC)
            elapsed = (now - started).total_seconds()
            
            if elapsed > hard_timeout:
                return True, f"Hard timeout exceeded ({elapsed:.0f}s > {hard_timeout}s)"
        
        # 2. Check for loops
        logs = manager.store.tail_log(agent_id, stream='stdout', tail=500)
        is_loop, reason = detector.detect(logs, agent_id)
        if is_loop:
            return True, f"Loop detected: {reason}"
        
        return False, None
        
    except Exception as e:
        logger.error(f"Error checking agent {agent_id}: {e}", exc_info=True)
        return False, None


def kill_agent(
    manager: AgentManager,
    agent_id: str,
    reason: str,
    metrics: 'AgentMetrics' | None = None,
    config: WatchdogConfig | None = None
) -> bool:
    """Kill agent and log reason."""
    try:
        logger.info(f"Killing agent {agent_id}: {reason}")
        manager.cancel(agent_id, force=True)
        
        # Log the kill reason
        manager.store.update_status(
            agent_id,
            AGENT_STATUS_TIMEOUT_HARD,
            error=f"Watchdog: {reason}",
            completed=True
        )
        logger.info(f"✓ Agent {agent_id} terminated")
        
        # Record metric
        if metrics:
            metrics.record(
                'watchdog_kill',
                agent_id=agent_id,
                reason=reason
            )
        
        # Check if should retry
        if metrics and config and 'loop' in reason.lower():
            metrics.record('loop_detected', agent_id=agent_id, reason=reason)
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to kill agent {agent_id}: {e}")
        return False


def run_watchdog(
    manager: AgentManager,
    detector: LoopDetector,
    hard_timeout: int,
    metrics: 'AgentMetrics' | None = None,
    config: WatchdogConfig | None = None
):
    """Exécute la boucle de surveillance."""
    logger.info("Watchdog started")
    
    agents = manager.list(status=AGENT_STATUS_RUNNING, include_completed=False)
    running = agents.get('agents', [])
    
    if not running:
        logger.debug("No running agents to monitor")
        return
    
    logger.info(f"Monitoring {len(running)} running agent(s)")
    
    for agent_info in running:
        agent_id = agent_info['agent_id']
        should_kill, reason = check_agent_health(
            manager,
            agent_id,
            detector,
            hard_timeout
        )
        
        if should_kill:
            kill_agent(manager, agent_id, reason, metrics=metrics, config=config)
    
    # Check alerts
    if metrics and config:
        alerts = metrics.check_alerts(config.config)
        for alert in alerts:
            logger.warning(alert)
            metrics.record('alert', message=alert)
    
    logger.info("Watchdog check complete")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Monitor and kill looping agents"
    )
    parser.add_argument(
        '--config',
        type=Path,
        default=None,
        help='Path to scheduler.yaml'
    )
    parser.add_argument(
        '--agent-id',
        type=str,
        default=None,
        help='Check specific agent (debug)'
    )
    
    args = parser.parse_args(argv)
    
    try:
        # 1. Load config
        config = WatchdogConfig(args.config)
        
        if not config.enabled:
            logger.info("Watchdog disabled in config")
            return 0
        
        logger.info("Watchdog enabled")
        
        # 2. Initialize metrics
        metrics = get_metrics_instance(BASE_DIR, config.config)
        
        # 3. Initialize AgentManager
        storage_dir = BASE_DIR / 'data' / 'agents'
        manager = AgentManager(storage_dir=storage_dir)
        logger.info(f"AgentManager initialized at {storage_dir}")
        
        # 4. Initialize detector
        detector = LoopDetector(config)
        logger.info(f"Loaded {len(config.loop_patterns)} loop detection patterns")
        
        # 5. Run watchdog
        if args.agent_id:
            # Debug mode: check specific agent
            logger.info(f"Debug mode: checking agent {args.agent_id}")
            should_kill, reason = check_agent_health(
                manager,
                args.agent_id,
                detector,
                config.hard_timeout
            )
            if should_kill:
                logger.info(f"Would kill: {reason}")
                # Uncomment to actually kill:
                # kill_agent(manager, args.agent_id, reason, metrics=metrics, config=config)
            else:
                logger.info("Agent healthy")
        else:
            # Normal mode: monitor all
            run_watchdog(manager, detector, config.hard_timeout, metrics=metrics, config=config)
        
        return 0
        
    except Exception as e:
        logger.error(f"Watchdog error: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
