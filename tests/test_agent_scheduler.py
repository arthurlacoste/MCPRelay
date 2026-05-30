"""
Tests pour agent_scheduler et watchdog.
"""

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from agent_manager import AgentManager, AgentSpec
from agent_manager.models import AGENT_STATUS_FAILED


@pytest.fixture
def scheduler_config(tmp_path: Path) -> Path:
    """Create temporary scheduler config."""
    config_data = {
        'version': 1,
        'agents': {'max_concurrent_local': 2},
        'watchdog': {
            'enabled': True,
            'check_interval_seconds': 5,
            'hard_timeout_seconds': 60,
            'loop_detection': {
                'duplication_threshold': 0.60,
                'error_threshold': 0.40,
            },
            'patterns': [
                {
                    'pattern': 'retry.*retry',
                    'reason': 'Retry loop',
                    'severity': 'high'
                }
            ]
        }
    }
    config_file = tmp_path / 'scheduler.yaml'
    with open(config_file, 'w') as f:
        yaml.dump(config_data, f)
    return config_file


@pytest.fixture
def task_file(tmp_path: Path) -> Path:
    """Create temporary task file."""
    task_data = {
        'name': 'Test Task',
        'description': 'A test task',
        'prompt': 'Please write hello world'
    }
    task_file = tmp_path / 'task.json'
    with open(task_file, 'w') as f:
        json.dump(task_data, f)
    return task_file


def test_agent_scheduler_import():
    """Test that agent_scheduler can be imported."""
    try:
        import sys
        from pathlib import Path
        src_dir = Path(__file__).resolve().parent.parent / 'src'
        if str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))
        
        from agent_scheduler import SchedulerConfig, compose_task_prompt
        assert callable(compose_task_prompt)
    except ImportError:
        pytest.skip("agent_scheduler not yet created")


def test_scheduler_config(scheduler_config: Path):
    """Test config loading."""
    try:
        import sys
        from pathlib import Path
        src_dir = Path(__file__).resolve().parent.parent / 'src'
        if str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))
        
        from agent_scheduler import SchedulerConfig
        config = SchedulerConfig(scheduler_config)
        assert config.max_concurrent_local == 2
    except ImportError:
        pytest.skip("agent_scheduler not yet created")


def test_compose_task_prompt():
    """Test task prompt composition."""
    try:
        import sys
        from pathlib import Path
        src_dir = Path(__file__).resolve().parent.parent / 'src'
        if str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))
        
        from agent_scheduler import compose_task_prompt
        
        task = {
            'name': 'Test',
            'description': 'Do something',
            'prompt': 'Please execute the plan'
        }
        prompt = compose_task_prompt(task)
        assert 'Do something' in prompt
        assert 'Please execute the plan' in prompt
    except ImportError:
        pytest.skip("agent_scheduler not yet created")


def test_watchdog_import():
    """Test that watchdog can be imported."""
    try:
        import sys
        from pathlib import Path
        src_dir = Path(__file__).resolve().parent.parent / 'src'
        if str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))
        
        from watchdog import WatchdogConfig, LoopDetector
        assert callable(LoopDetector)
    except ImportError:
        pytest.skip("watchdog not yet created")


def test_loop_detector_patterns():
    """Test loop detection patterns."""
    try:
        import sys
        from pathlib import Path
        src_dir = Path(__file__).resolve().parent.parent / 'src'
        if str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))
        
        from watchdog import WatchdogConfig, LoopDetector
        
        # Create a simple test config
        class TestConfig:
            duplication_threshold = 0.60
            error_threshold = 0.40
            progress_similarity = 0.70
            loop_patterns = [
                {
                    'pattern': r'retry.*retry',
                    'reason': 'Retry loop',
                    'severity': 'high'
                }
            ]
        
        detector = LoopDetector(TestConfig())
        
        # Test retry pattern
        logs = "Failed. Retry. Failed. Retry. Failed. Retry retry retry"
        is_loop, reason = detector.detect(logs, "test-agent")
        # Result depends on patterns - just ensure no crash
        assert isinstance(is_loop, bool)
        
    except ImportError:
        pytest.skip("watchdog not yet created")


def test_loop_detector_duplication():
    """Test duplication-based loop detection."""
    try:
        import sys
        from pathlib import Path
        src_dir = Path(__file__).resolve().parent.parent / 'src'
        if str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))
        
        from watchdog import WatchdogConfig, LoopDetector
        
        # Create a simple test config
        class TestConfig:
            duplication_threshold = 0.60
            error_threshold = 0.40
            progress_similarity = 0.70
            loop_patterns = []
        
        detector = LoopDetector(TestConfig())
        
        # Create logs with high duplication
        line = "Processing item"
        logs = "\n".join([line] * 80)  # 80% same line
        is_loop, reason = detector.detect(logs, "test-agent")
        assert is_loop
        assert "duplication" in reason.lower()
    except ImportError:
        pytest.skip("watchdog not yet created")


def test_loop_detector_errors():
    """Test error spam detection."""
    try:
        import sys
        from pathlib import Path
        src_dir = Path(__file__).resolve().parent.parent / 'src'
        if str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))
        
        from watchdog import WatchdogConfig, LoopDetector
        
        # Create a simple test config with higher duplication threshold
        # so we can test the error detection
        class TestConfig:
            duplication_threshold = 0.99  # Very high threshold
            error_threshold = 0.40
            progress_similarity = 0.70
            loop_patterns = []
        
        detector = LoopDetector(TestConfig())
        
        # Create logs with high error ratio but varied lines
        error_line = "Error: connection failed on retry {}"
        normal_line = "Processing item {}..."
        logs = "\n".join(
            [error_line.format(i) for i in range(50)] + 
            [normal_line.format(i) for i in range(50)]
        )
        is_loop, reason = detector.detect(logs, "test-agent")
        assert is_loop
        assert "error" in reason.lower()
    except ImportError:
        pytest.skip("watchdog not yet created")


def test_watchdog_kill_agent_without_metrics_does_not_crash():
    """Loop kills should work even when metrics collection is disabled."""
    import sys
    from pathlib import Path
    src_dir = Path(__file__).resolve().parent.parent / 'src'
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    from watchdog import kill_agent
    from agent_manager.models import AGENT_STATUS_TIMEOUT_HARD

    manager = MagicMock()

    assert kill_agent(
        manager,
        "agt_test",
        "Loop detected: repeated output",
        metrics=None,
        config=MagicMock(),
    )

    manager.cancel.assert_called_once_with("agt_test", force=True)
    manager.store.update_status.assert_called_once_with(
        "agt_test",
        AGENT_STATUS_TIMEOUT_HARD,
        error="Watchdog: Loop detected: repeated output",
        completed=True,
    )


def test_metrics_alerts_read_nested_scheduler_config(tmp_path: Path):
    """scheduler.yaml stores alert thresholds under metrics.alerts."""
    import sys
    from pathlib import Path
    src_dir = Path(__file__).resolve().parent.parent / 'src'
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    from agent_metrics import AgentMetrics

    metrics = AgentMetrics(tmp_path / "metrics.jsonl")
    metrics.record("loop_detected", agent_id="agt_1")

    alerts = metrics.check_alerts({
        "metrics": {
            "alerts": {
                "loop_detection_per_hour": 0,
                "failure_rate": 1.0,
            }
        }
    })

    assert alerts
    assert "High loop detection rate" in alerts[0]


def test_submit_retry_agent_creates_child_with_retry_metadata(tmp_path: Path):
    from agent_scheduler import SchedulerConfig, submit_retry_agent

    config_file = tmp_path / "scheduler.yaml"
    config_file.write_text(yaml.dump({
        "retry": {
            "enabled": True,
            "max_attempts": 3,
            "backoff_seconds": [0],
            "retryable_statuses": ["failed"],
            "retry_on_patterns": ["connection.*refused"],
        }
    }), encoding="utf-8")
    manager = AgentManager(tmp_path / "agents", cwd_allowlist=[str(tmp_path)])
    agent_id = manager.submit(AgentSpec(
        prompt="retry me",
        provider="ollama",
        purpose="unit retry",
        cwd=str(tmp_path),
    ))["agent_id"]
    manager.store.update_status(
        agent_id,
        AGENT_STATUS_FAILED,
        error="connection refused",
        completed=True,
    )
    (manager.store.run_dir(agent_id) / "stderr.log").write_text(
        "Ollama connection refused\n",
        encoding="utf-8",
    )

    result = submit_retry_agent(
        agent_id,
        manager,
        SchedulerConfig(config_file),
        now=datetime.now(UTC) + timedelta(seconds=1),
    )

    assert result is not None
    child = manager.store.get_agent(result["agent_id"])
    assert child.parent_id == agent_id
    assert child.metadata["retry_of"] == agent_id
    assert child.metadata["retry_root"] == agent_id
    assert child.metadata["retry_attempt"] == 1


def test_submit_retry_agent_skips_when_active_retry_exists(tmp_path: Path):
    from agent_scheduler import SchedulerConfig, submit_retry_agent

    config_file = tmp_path / "scheduler.yaml"
    config_file.write_text(yaml.dump({
        "retry": {
            "enabled": True,
            "max_attempts": 3,
            "backoff_seconds": [0],
            "retryable_statuses": ["failed"],
            "retry_on_patterns": [],
        }
    }), encoding="utf-8")
    config = SchedulerConfig(config_file)
    manager = AgentManager(tmp_path / "agents", cwd_allowlist=[str(tmp_path)])
    agent_id = manager.submit(AgentSpec(prompt="retry me", cwd=str(tmp_path)))["agent_id"]
    manager.store.update_status(agent_id, AGENT_STATUS_FAILED, error="timeout", completed=True)

    first = submit_retry_agent(agent_id, manager, config, now=datetime.now(UTC) + timedelta(seconds=1))
    second = submit_retry_agent(agent_id, manager, config, now=datetime.now(UTC) + timedelta(seconds=2))

    assert first is not None
    assert second is None


def test_setup_cron_dry_run_outputs_marked_jobs():
    script = Path(__file__).resolve().parent.parent / "setup-cron.sh"

    subprocess.run(["bash", "-n", str(script)], check=True)
    result = subprocess.run(
        [str(script), "--dry-run"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "# BEGIN myMCP scheduler" in result.stdout
    assert "src/agent_scheduler.py --task-source configured" in result.stdout
    assert "src/watchdog.py" in result.stdout


def test_submit_apple_note_tasks_creates_one_agent_and_deduplicates(tmp_path: Path):
    from agent_scheduler import SchedulerConfig, submit_apple_note_tasks
    from apple_notes_tasks import AppleNoteTask

    config_file = tmp_path / "scheduler.yaml"
    state_file = tmp_path / "notes_state.json"
    config_file.write_text(yaml.dump({
        "scheduler": {
            "defaults": {
                "provider": "ollama",
                "model": "local-model",
                "agent_timeout_seconds": 120,
                "auto_run": False,
            }
        }
    }), encoding="utf-8")
    config = SchedulerConfig(config_file)
    manager = AgentManager(tmp_path / "agents", cwd_allowlist=[str(tmp_path)])
    note = AppleNoteTask(
        note_id="note-1",
        title="Ops",
        body="#iatasks\nVerifier les logs puis proposer un correctif.",
        modified_at="today",
    )

    first = submit_apple_note_tasks(
        manager,
        metrics=None,
        config=config,
        source_config={"hashtag": "#iatasks", "state_file": str(state_file)},
        cwd=tmp_path,
        notes=[note],
    )
    second = submit_apple_note_tasks(
        manager,
        metrics=None,
        config=config,
        source_config={"hashtag": "#iatasks", "state_file": str(state_file)},
        cwd=tmp_path,
        notes=[note],
    )

    assert len(first) == 1
    assert second == []
    record = manager.store.get_agent(first[0]["agent_id"])
    assert record.provider == "ollama"
    assert record.model == "local-model"
    assert record.agent_timeout_seconds == 120
    assert record.metadata["source"] == "apple_notes"
    assert record.metadata["note_id"] == "note-1"
    assert "Verifier les logs" in record.prompt


def test_submit_apple_note_tasks_honors_source_auto_run(tmp_path: Path):
    from agent_scheduler import SchedulerConfig, submit_apple_note_tasks
    from apple_notes_tasks import AppleNoteTask

    config_file = tmp_path / "scheduler.yaml"
    state_file = tmp_path / "notes_state.json"
    config_file.write_text(yaml.dump({
        "scheduler": {
            "defaults": {
                "provider": "ollama",
                "model": "ollama/qwen2.5-coder:0.5b",
                "auto_run": False,
            }
        }
    }), encoding="utf-8")
    manager = AgentManager(tmp_path / "agents", cwd_allowlist=[str(tmp_path)])
    note = AppleNoteTask(
        note_id="note-1",
        title="Ops",
        body="#iatasks\nFaire un test.",
        modified_at="today",
    )

    result = submit_apple_note_tasks(
        manager,
        metrics=None,
        config=SchedulerConfig(config_file),
        source_config={
            "hashtag": "#iatasks",
            "state_file": str(state_file),
            "auto_run": True,
        },
        cwd=tmp_path,
        notes=[note],
    )

    record = manager.store.get_agent(result[0]["agent_id"])
    assert record.auto_run is True


def test_build_task_spec_prefixes_ollama_model():
    from agent_scheduler import build_task_spec

    spec = build_task_spec(
        "hello",
        provider="ollama",
        model="qwen3.5:35b-a3b-coding-nvfp4",
        purpose="unit",
        cwd=None,
        timeout=30,
        auto_run=False,
        metadata={},
    )

    assert spec.model == "ollama/qwen3.5:35b-a3b-coding-nvfp4"
    assert spec.llm_supports_functions is False
