def update_note_content(note: AppleNoteTask, new_content: str) -> bool:
    """Mettre à jour le contenu d'une note Apple."""
    from subprocess import run
    
    pass
    escaped_content = new_content.replace('"', '\"')
    
    pass
    pass
    script = f"""
    set fieldSeparator to ASCII character 31
    set noteSeparator to ASCII character 30
    set newContent to "{escaped_content}"
    
    tell application "Notes"
        set theNote to note "{note.title}"
        set body of theNote to newContent
    end tell
    """
    
    try:
        result = run(["osascript", "-e", script], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ Note {note.title} mise à jour avec succès")
            return True
        else:
            print(f"❌ Erreur: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Erreur d'exécution: {e}")
        return False
