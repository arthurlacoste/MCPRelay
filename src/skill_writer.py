from __future__ import annotations

import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Mapping

from skill_catalog import MAX_FILE_BYTES, _parse_skill, _validate_skill_id, get_skills_root

MAX_FILE_COUNT = 32
MAX_PACKAGE_BYTES = 1024 * 1024
BUILTIN_SKILLS_ROOT = Path(__file__).resolve().parent / "builtin_skills"


def _validate_text(content: object, label: str) -> str:
    if not isinstance(content, str):
        raise TypeError(f"{label} must be text")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError(f"file exceeds {MAX_FILE_BYTES} bytes: {label}")
    if any(ord(char) < 32 and char not in {"\t", "\n", "\r"} for char in content) or "\x7f" in content:
        raise ValueError(f"binary files are not supported: {label}")
    return content


def _validate_package_path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise ValueError("path must be a non-empty string")
    if "\\" in value:
        raise ValueError("path must use POSIX separators")
    parts = value.split("/")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError("path must be relative")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("path must not contain empty, current, or parent segments")
    if path.as_posix() == "SKILL.md":
        raise ValueError("SKILL.md must be provided through skill_md")
    return path


def validate_package_files(skill_md: object, additional_files: Mapping[str, object] | None = None) -> dict[str, str]:
    skill_text = _validate_text(skill_md, "skill_md")
    if not skill_text.strip():
        raise ValueError("skill_md must be non-empty")
    if additional_files is None:
        additional_files = {}
    if not isinstance(additional_files, Mapping):
        raise TypeError("additional_files must be a mapping of paths to text")
    if len(additional_files) + 1 > MAX_FILE_COUNT:
        raise ValueError(f"package may contain at most {MAX_FILE_COUNT} files")

    files = {"SKILL.md": skill_text}
    total = len(skill_text.encode("utf-8"))
    for raw_path, raw_content in additional_files.items():
        path = _validate_package_path(raw_path).as_posix()
        content = _validate_text(raw_content, path)
        total += len(content.encode("utf-8"))
        if total > MAX_PACKAGE_BYTES:
            raise ValueError(f"package exceeds {MAX_PACKAGE_BYTES} bytes")
        files[path] = content
    if total > MAX_PACKAGE_BYTES:
        raise ValueError(f"package exceeds {MAX_PACKAGE_BYTES} bytes")
    return files


def _reject_symlink_components(root: Path, relative: PurePosixPath) -> None:
    current = root
    if current.is_symlink():
        raise ValueError("skills root must not be a symlink")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symlinked path component is not allowed: {part}")
        if current.exists() and not current.is_dir():
            raise ValueError(f"path component is not a directory: {part}")


def atomic_write_package(
    target: Path,
    files: Mapping[str, str],
    skill_id: str,
    *,
    skills_root: Path,
) -> None:
    relative_parent = PurePosixPath(target.parent.relative_to(skills_root).as_posix())
    _reject_symlink_components(skills_root, relative_parent)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(skills_root, relative_parent)
    temp_path = Path(tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=parent))
    try:
        _reject_symlink_components(skills_root, relative_parent)
        for relative, content in files.items():
            destination = temp_path.joinpath(*PurePosixPath(relative).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8", newline="")
        _parse_skill(temp_path / "SKILL.md", skill_id, temp_path)
        _reject_symlink_components(skills_root, relative_parent)
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"skill already exists: {skill_id}")
        temp_path.replace(target)
    finally:
        if temp_path.exists() or temp_path.is_symlink():
            shutil.rmtree(temp_path, ignore_errors=True)


def create_skill(skill_id: str, skill_md: str, additional_files: Mapping[str, str] | None = None, *, root: Path | None = None) -> dict:
    validated_id = _validate_skill_id(skill_id)
    files = validate_package_files(skill_md, additional_files)
    skills_root = Path(root or get_skills_root()).expanduser()
    relative = PurePosixPath(validated_id)

    if skills_root.is_symlink():
        raise ValueError("skills root must not be a symlink")
    skills_root.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(skills_root, relative)
    target = skills_root.joinpath(*relative.parts)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"skill already exists: {validated_id}")

    atomic_write_package(target, files, validated_id, skills_root=skills_root)
    skill = _parse_skill(target / "SKILL.md", validated_id, target)
    return {"created": True, "skill": skill.summary(), "files": sorted(files)}


def install_builtin_skills(*, root: Path | None = None, source_root: Path | None = None) -> list[str]:
    skills_root = Path(root or get_skills_root()).expanduser()
    builtins = Path(source_root or BUILTIN_SKILLS_ROOT)
    if not builtins.is_dir():
        return []

    installed: list[str] = []
    for source in sorted(path for path in builtins.iterdir() if path.is_dir()):
        skill_file = source / "SKILL.md"
        if not skill_file.is_file():
            continue
        skill_id = f"gate/{source.name}"
        target = skills_root / "gate" / source.name
        if target.exists() or target.is_symlink():
            continue
        additional = {
            path.relative_to(source).as_posix(): path.read_text(encoding="utf-8")
            for path in source.rglob("*")
            if path.is_file() and path.name != "SKILL.md"
        }
        create_skill(skill_id, skill_file.read_text(encoding="utf-8"), additional, root=skills_root)
        installed.append(skill_id)
    return installed
