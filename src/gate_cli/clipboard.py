from __future__ import annotations

import shutil
import subprocess


def copy_text(value: str) -> bool:
    for command in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        if shutil.which(command[0]):
            subprocess.run(command, input=value, text=True, check=True)
            return True
    return False
