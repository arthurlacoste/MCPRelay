from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

DEFAULT_SKILLS_ROOT = '~/.gate/skills'
MAX_FILE_BYTES = 256 * 1024


@dataclass(frozen=True)
class Skill:
    skill_id: str
    name: str
    description: str
    package_dir: Path
    skill_file: Path

    def summary(self) -> dict[str, str]:
        return {
            'id': self.skill_id,
            'name': self.name,
            'description': self.description,
        }


def get_skills_root(environ: dict[str, str] | os._Environ[str] | None = None) -> Path:
    env = environ if environ is not None else os.environ
    return Path(env.get('MCP_SKILLS_ROOT', DEFAULT_SKILLS_ROOT)).expanduser()


def _parse_skill(path: Path, root: Path) -> Skill:
    text = _read_utf8(path)
    if not text.startswith('---'):
        raise ValueError('missing YAML frontmatter')

    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        raise ValueError('frontmatter must start on the first line')
    try:
        closing = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == '---')
    except StopIteration as exc:
        raise ValueError('unterminated YAML frontmatter') from exc

    try:
        metadata = yaml.safe_load('\n'.join(lines[1:closing]))
    except yaml.YAMLError as exc:
        raise ValueError(f'invalid YAML frontmatter: {exc}') from exc
    if not isinstance(metadata, dict):
        raise ValueError('frontmatter must be a YAML mapping')

    name = metadata.get('name')
    description = metadata.get('description')
    if not isinstance(name, str) or not name.strip():
        raise ValueError('frontmatter name must be a non-empty string')
    if not isinstance(description, str) or not description.strip():
        raise ValueError('frontmatter description must be a non-empty string')

    package_dir = path.parent
    skill_id = package_dir.relative_to(root).as_posix()
    return Skill(skill_id, name.strip(), description.strip(), package_dir, path)


def scan_skills(root: Path | None = None) -> tuple[list[Skill], list[str]]:
    root = root or get_skills_root()
    warnings: list[str] = []
    if not root.exists():
        warnings.append(
            f'Skills root does not exist: {root}. Set MCP_SKILLS_ROOT or create ~/.gate/skills.'
        )
        return [], warnings
    if not root.is_dir():
        return [], [f'Skills root is not a directory: {root}']

    root = root.resolve()
    skills: list[Skill] = []
    for path in sorted(root.rglob('SKILL.md')):
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root):
                warnings.append(f'Excluded {path}: resolves outside the skills root')
                continue
            skills.append(_parse_skill(resolved, root))
        except (OSError, UnicodeError, ValueError) as exc:
            relative = path.relative_to(root).as_posix()
            warnings.append(f'Excluded {relative}: {exc}')
    return skills, warnings


def _rank(skill: Skill, query: str) -> tuple[int, int, str]:
    needle = query.casefold().strip()
    skill_id = skill.skill_id.casefold()
    name = skill.name.casefold()
    description = skill.description.casefold()
    fields = (skill_id, name, description)

    if needle in {skill_id, name}:
        tier = 0
    elif skill_id.startswith(needle) or name.startswith(needle):
        tier = 1
    elif needle in skill_id or needle in name:
        tier = 2
    elif needle in description:
        tier = 3
    else:
        words = [word for word in needle.split() if word]
        matched = sum(any(word in field for field in fields) for word in words)
        if not words or matched == 0:
            return (99, 0, skill.skill_id)
        tier = 4
        return (tier, -matched, skill.skill_id)
    return (tier, 0, skill.skill_id)


def skills_search(
    query: str | None = None,
    limit: int = 8,
    offset: int = 0,
    root: Path | None = None,
) -> dict[str, Any]:
    limit = max(1, min(int(limit), 50))
    offset = max(0, int(offset))
    skills, warnings = scan_skills(root)

    if query is None or not query.strip():
        ordered = sorted(skills, key=lambda skill: (skill.name.casefold(), skill.skill_id))
    else:
        ranked = [( _rank(skill, query), skill) for skill in skills]
        ordered = [skill for rank, skill in sorted(ranked, key=lambda item: item[0]) if rank[0] < 99]

    total = len(ordered)
    page = ordered[offset:offset + limit]
    return {
        'matches': [skill.summary() for skill in page],
        'total': total,
        'has_more': offset + len(page) < total,
        'warnings': warnings,
    }


def _validate_relative_path(path: str) -> PurePosixPath:
    raw_parts = path.replace('\\', '/').split('/')
    candidate = PurePosixPath(path)
    if candidate.is_absolute():
        raise ValueError('path must be relative')
    if not raw_parts or any(part in {'', '.', '..'} for part in raw_parts):
        raise ValueError('path must not contain empty, current, or parent segments')
    return candidate


def _read_utf8(path: Path) -> str:
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(f'file exceeds {MAX_FILE_BYTES} bytes')
    data = path.read_bytes()
    if b'\x00' in data:
        raise ValueError('binary files are not supported')
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError('file must be valid UTF-8 text') from exc


def _available_files(skill: Skill) -> list[str]:
    files: list[str] = []
    package = skill.package_dir.resolve()
    for candidate in sorted(skill.package_dir.rglob('*')):
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file() and resolved.is_relative_to(package):
            files.append(candidate.relative_to(skill.package_dir).as_posix())
    return files


def skills_read(skill_id: str, path: str = 'SKILL.md', root: Path | None = None) -> dict[str, Any]:
    root = (root or get_skills_root())
    skills, warnings = scan_skills(root)
    by_id = {skill.skill_id: skill for skill in skills}
    skill = by_id.get(skill_id)
    if skill is None:
        detail = f" Available warnings: {'; '.join(warnings)}" if warnings else ''
        raise ValueError(f'unknown skill_id: {skill_id}.{detail}')

    relative = _validate_relative_path(path)
    package = skill.package_dir.resolve()
    candidate = skill.package_dir.joinpath(*relative.parts)
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(f'file not found: {path}') from exc
    if not resolved.is_relative_to(package):
        raise ValueError('path resolves outside the skill package')
    if not resolved.is_file():
        raise ValueError('path must reference a file')

    content = _read_utf8(resolved)
    return {
        'id': skill.skill_id,
        'name': skill.name,
        'description': skill.description,
        'path': relative.as_posix(),
        'content': content,
        'files': _available_files(skill),
    }
