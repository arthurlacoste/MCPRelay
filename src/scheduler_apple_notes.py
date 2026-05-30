from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_manager import AgentManager, AgentSpec
from apple_notes_tasks import (
    AppleNotesState,
    AppleNoteTask,
    compose_note_agent_prompt,
    fetch_notes_with_hashtag,
)


logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent


def resolve_config_path(path_value: str | Path, base_dir: Path) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else base_dir / path


def apple_notes_state_path(source_config: dict[str, Any], base_dir: Path) -> Path:
    return resolve_config_path(source_config.get('state_file', 'data/apple_notes_tasks_state.json'), base_dir)


def submit_apple_note_tasks(
    manager: AgentManager,
    metrics,
    config,
    source_config: dict[str, Any],
    *,
    base_dir: Path = BASE_DIR,
    provider: str | None = None,
    model: str | None = None,
    cwd: Path | None = None,
    timeout: int | None = None,
    auto_run: bool | None = None,
    notes: list[AppleNoteTask] | None = None,
) -> list[dict[str, Any]]:
    hashtag = source_config.get('hashtag', '#iatasks')
    state = AppleNotesState(apple_notes_state_path(source_config, base_dir))
    notes = notes if notes is not None else fetch_notes_with_hashtag(hashtag)
    defaults = config.defaults
    submitted = []
    for note in notes:
        if state.has_processed(note):
            logger.info(f"Skipping unchanged Apple Note: {note.title}")
            continue
        spec = AgentSpec(
            prompt=compose_note_agent_prompt(note),
            provider=provider or source_config.get('provider') or defaults.get('provider', 'ollama'),
            model=model or source_config.get('model') or defaults.get('model'),
            purpose=f"Apple Notes: {note.title}",
            cwd=str(cwd) if cwd else None,
            agent_timeout_seconds=timeout or source_config.get('agent_timeout_seconds') or defaults.get('agent_timeout_seconds', 300),
            auto_run=auto_run if auto_run is not None else bool(source_config.get('auto_run', defaults.get('auto_run', False))),
            llm_supports_functions=(provider or source_config.get('provider') or defaults.get('provider', 'ollama')) != 'ollama',
            metadata={
                'scheduled': True,
                'scheduled_at': datetime.now(UTC).isoformat(),
                'source': 'apple_notes',
                'note_id': note.note_id,
                'note_title': note.title,
                'note_modified_at': note.modified_at,
                'note_fingerprint': note.fingerprint,
                'hashtag': hashtag,
            },
        )
        result = manager.submit(spec)
        if metrics:
            metrics.record(
                'agent_submitted',
                agent_id=result['agent_id'],
                provider=spec.provider,
                purpose=spec.purpose,
                retry_of=None,
                source='apple_notes',
            )
        state.mark_processed(note, result['agent_id'])
        submitted.append(result)
    return submitted
