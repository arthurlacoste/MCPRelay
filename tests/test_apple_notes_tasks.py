from pathlib import Path

from apple_notes_tasks import (
    FIELD_SEPARATOR,
    NOTE_SEPARATOR,
    AppleNotesState,
    AppleNoteTask,
    apple_notes_script,
    compose_note_agent_prompt,
    marker_variants,
    parse_notes_output,
)


def test_parse_notes_output_strips_html_and_keeps_note_metadata():
    raw = FIELD_SEPARATOR.join([
        "x-coredata://note/1",
        "Projet",
        "Thursday 28 May 2026 at 06:30:00",
        "<div>#iatasks</div><div>Verifier les logs</div>",
    ]) + NOTE_SEPARATOR

    notes = parse_notes_output(raw)

    assert len(notes) == 1
    assert notes[0].note_id == "x-coredata://note/1"
    assert notes[0].title == "Projet"
    assert "#iatasks" in notes[0].body
    assert "Verifier les logs" in notes[0].body


def test_apple_notes_state_deduplicates_same_note_version(tmp_path: Path):
    note = AppleNoteTask(
        note_id="note-1",
        title="Ops",
        body="#iatasks\nFaire un controle",
        modified_at="today",
    )
    state = AppleNotesState(tmp_path / "state.json")

    assert not state.has_processed(note)

    state.mark_processed(note, "agt_1")
    reloaded = AppleNotesState(tmp_path / "state.json")

    assert reloaded.has_processed(note)
    changed = AppleNoteTask(
        note_id="note-1",
        title="Ops",
        body="#iatasks\nFaire un controle modifie",
        modified_at="later",
    )
    assert not reloaded.has_processed(changed)


def test_compose_note_agent_prompt_uses_full_note_and_local_constraints():
    note = AppleNoteTask(
        note_id="note-1",
        title="Ops",
        body="#iatasks\nAnalyser le scheduler",
        modified_at="today",
    )

    prompt = compose_note_agent_prompt(note)

    assert "Ops" in prompt
    assert "Analyser le scheduler" in prompt
    assert "mode local" in prompt
    assert "N'envoie pas de mail" in prompt


def test_hashtag_marker_variants_include_apple_notes_tagline():
    assert marker_variants("#iatasks") == ["#iatasks", "-iatasks"]

    script = apple_notes_script("#iatasks")

    assert 'noteBody contains "#iatasks"' in script
    assert 'noteText contains "-iatasks"' in script
