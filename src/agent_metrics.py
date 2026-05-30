#!/usr/bin/env python3
"""
Agent Metrics — Collect and record scheduler/watchdog metrics.

Logs all events to JSONL for analysis and alerting.
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AgentMetrics:
    """Record scheduler and watchdog metrics."""
    
    def __init__(self, output_file: Path):
        self.output_file = Path(output_file)
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
    
    def record(self, event: str, **kwargs) -> None:
        """Record a metrics event to JSONL."""
        try:
            record = {
                "timestamp": datetime.now(UTC).isoformat(),
                "event": event,
                **kwargs
            }
            
            with open(self.output_file, 'a') as f:
                f.write(json.dumps(record, default=str) + '\n')
            
            # Log as well
            logger.debug(f"Metric recorded: {event} {kwargs}")
            
        except Exception as e:
            logger.error(f"Failed to record metric: {e}", exc_info=True)
    
    def get_recent_events(self, event_type: str, hours: int = 1) -> list[dict[str, Any]]:
        """Get recent events of a specific type."""
        try:
            if not self.output_file.exists():
                return []
            
            cutoff = datetime.now(UTC).timestamp() - (hours * 3600)
            events = []
            
            with open(self.output_file, 'r') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        ts = datetime.fromisoformat(record['timestamp']).timestamp()
                        if ts >= cutoff and record.get('event') == event_type:
                            events.append(record)
                    except json.JSONDecodeError:
                        continue
            
            return events
        
        except Exception as e:
            logger.error(f"Error reading metrics: {e}")
            return []
    
    def count_events(self, event_type: str, hours: int = 1) -> int:
        """Count events of a specific type."""
        return len(self.get_recent_events(event_type, hours))

    def count_recent_events(self, hours: int = 1) -> dict[str, int]:
        """Count all recent events grouped by event name."""
        counts: dict[str, int] = {}
        try:
            if not self.output_file.exists():
                return counts

            cutoff = datetime.now(UTC).timestamp() - (hours * 3600)
            with open(self.output_file, 'r') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        ts = datetime.fromisoformat(record['timestamp']).timestamp()
                    except (KeyError, ValueError, json.JSONDecodeError):
                        continue
                    if ts < cutoff:
                        continue
                    event = str(record.get('event') or 'unknown')
                    counts[event] = counts.get(event, 0) + 1
        except Exception as e:
            logger.error(f"Error counting metrics: {e}")
        return counts
    
    def check_alerts(self, config: dict[str, Any]) -> list[str]:
        """Check if any alert thresholds are exceeded."""
        alerts = []
        alerts_config = config.get('alerts') or config.get('metrics', {}).get('alerts', {})
        
        # Check loop detection rate
        loop_threshold = alerts_config.get('loop_detection_per_hour', 5)
        loop_count = self.count_events('loop_detected', hours=1)
        if loop_count > loop_threshold:
            alerts.append(f"⚠ High loop detection rate: {loop_count} loops in last hour (threshold: {loop_threshold})")
        
        # Check failure rate
        failure_threshold = alerts_config.get('failure_rate', 0.30)
        recent_completed = self.count_events('agent_completed', hours=1)
        recent_failed = self.count_events('agent_failed', hours=1)
        
        if recent_completed > 0 or recent_failed > 0:
            total = recent_completed + recent_failed
            failure_rate = recent_failed / total if total > 0 else 0
            if failure_rate > failure_threshold:
                alerts.append(
                    f"⚠ High failure rate: {failure_rate:.0%} "
                    f"({recent_failed} failed, {recent_completed} succeeded in last hour)"
                )
        
        return alerts


def get_metrics_instance(base_dir: Path, config: dict[str, Any] | None = None) -> AgentMetrics:
    """Factory function to get or create metrics instance."""
    output_file = (config or {}).get('metrics', {}).get('output_file', 'logs/metrics.jsonl')
    metrics_file = Path(output_file)
    if not metrics_file.is_absolute():
        metrics_file = base_dir / metrics_file
    return AgentMetrics(metrics_file)
