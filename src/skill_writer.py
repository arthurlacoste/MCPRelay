from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import secrets
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator, Mapping

from skill_catalog import MAX_FILE_BYTES, get_skills_root, parse_skill_package, validate_skill_id

MAX_FILE_COUNT = 32
MAX_PACKAGE_BYTES = 1024 * 1024
BUILTIN_SKILLS_ROOT = Path(__file__).resolve().parent / "builtin_skills"
LOCK_STALE_SECONDS = 300
logger = logging.getLogger(__name__)


def _validate_text(content: object, label: str) -> tuple[str, bytes]:
    if not isinstance(content, str):
        raise TypeError(f"{label} must be text")
    try:
        encoded = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"invalid Unicode text: {label}") from exc
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError(f"file exceeds {MAX_FILE_BYTES} bytes: {label}")
    if any(ord(char) < 32 and char not in {"\t", "\n", "\r"} for char in content) or "\x7f" in content:
        raise ValueError(f"binary files are not supported: {label}")
    return content, encoded


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


def validate_package_files(
    skill_md: object,
    additional_files: Mapping[str, object] | None = None,
) -> dict[str, tuple[str, bytes]]:
    skill_text, skill_bytes = _validate_text(skill_md, "skill_md")
    if not skill_text.strip():
        raise ValueError("skill_md must be non-empty")
    if additional_files is None:
        additional_files = {}
    if not isinstance(additional_files, Mapping):
        raise TypeError("additional_files must be a mapping of paths to text")
    if len(additional_files) + 1 > MAX_FILE_COUNT:
        raise ValueError(f"package may contain at most {MAX_FILE_COUNT} files")

    files = {"SKILL.md": (skill_text, skill_bytes)}
    total = len(skill_bytes)
    for raw_path, raw_content in additional_files.items():
        path = _validate_package_path(raw_path).as_posix()
        content, encoded = _validate_text(raw_content, path)
        total += len(encoded)
        if total > MAX_PACKAGE_BYTES:
            raise ValueError(f"package exceeds {MAX_PACKAGE_BYTES} bytes")
        files[path] = (content, encoded)
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


@contextmanager
def _exclusive_creation_lock(skills_root: Path, skill_id: str) -> Iterator[None]:
    lock_name = hashlib.sha256(skill_id.encode("utf-8")).hexdigest()
    lock_path = skills_root / f".create-{lock_name}.lock"
    metadata = {"pid": os.getpid(), "created": time.time()}
    descriptor = -1
    acquired = False

    for attempt in range(2):
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            acquired = True
            break
        except FileExistsError as exc:
            if attempt or not _remove_stale_lock(lock_path):
                raise FileExistsError(f"skill creation already in progress: {skill_id}") from exc
    try:
        os.write(descriptor, json.dumps(metadata).encode("ascii"))
        opened_descriptor = descriptor
        descriptor = -1
        os.close(opened_descriptor)
        yield
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if acquired:
            lock_path.unlink(missing_ok=True)


def _remove_stale_lock(lock_path: Path) -> bool:
    try:
        metadata = json.loads(lock_path.read_text(encoding="ascii"))
        pid = int(metadata["pid"])
        created = float(metadata["created"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        try:
            age = max(0.0, time.time() - lock_path.stat().st_mtime)
        except FileNotFoundError:
            return True
        if age < LOCK_STALE_SECONDS:
            return False
    else:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            age = max(0.0, time.time() - created)
            if age < 1:
                return False
        except PermissionError:
            try:
                age = max(0.0, time.time() - lock_path.stat().st_mtime)
            except FileNotFoundError:
                return True
            if age < LOCK_STALE_SECONDS:
                return False
        else:
            return False

    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass
    return True


def _open_directory_at(parent_fd: int, name: str) -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return os.open(name, flags, dir_fd=parent_fd)


def _supports_secure_dir_fd_publication() -> bool:
    replace_parameters = inspect.signature(os.replace).parameters
    return (
        os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
        and "src_dir_fd" in replace_parameters
        and "dst_dir_fd" in replace_parameters
    )


def _open_or_create_parent_fd(skills_root: Path, relative: PurePosixPath) -> int | None:
    if not _supports_secure_dir_fd_publication():
        return None
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    current_fd = os.open(skills_root, flags)
    try:
        for part in relative.parts:
            try:
                next_fd = _open_directory_at(current_fd, part)
            except FileNotFoundError:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
                next_fd = _open_directory_at(current_fd, part)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _create_temp_directory_at(parent_fd: int, target_name: str) -> tuple[str, int]:
    for _ in range(100):
        name = f".{target_name}.tmp-{secrets.token_hex(8)}"
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            continue
        return name, _open_directory_at(parent_fd, name)
    raise FileExistsError(f"could not allocate temporary directory for {target_name}")


def _descriptor_path(descriptor: int) -> Path:
    for base in (Path("/proc/self/fd"), Path("/dev/fd")):
        candidate = base / str(descriptor)
        if candidate.exists():
            return candidate
    raise RuntimeError("descriptor-backed paths are unavailable on this platform")


def _descriptor_real_path(descriptor: int) -> Path:
    descriptor_path = _descriptor_path(descriptor)
    try:
        linked_path = Path(os.readlink(descriptor_path))
    except OSError:
        pass
    else:
        if linked_path.is_absolute() and linked_path != descriptor_path:
            return linked_path

    if sys.platform == "darwin":
        import fcntl

        try:
            # macOS PATH_MAX is 1024. fcntl returns the kernel-filled copy.
            buffer = fcntl.fcntl(descriptor, fcntl.F_GETPATH, bytes(1024))
        except (OSError, ValueError, BufferError, TypeError, AttributeError):
            pass
        else:
            raw_path = buffer.split(b"\0", 1)[0]
            if raw_path:
                return Path(os.fsdecode(raw_path))

    resolved = descriptor_path.resolve()
    if resolved == descriptor_path:
        raise RuntimeError("could not resolve descriptor-backed path")
    return resolved


def _write_package_tree(temp_path: Path, files: Mapping[str, tuple[str, bytes]]) -> None:
    for relative, (_, encoded) in files.items():
        destination = temp_path.joinpath(*PurePosixPath(relative).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(encoded)


def _atomic_write_package_dir_fd(
    target: Path,
    files: Mapping[str, tuple[str, bytes]],
    skill_id: str,
    *,
    skills_root: Path,
    relative_parent: PurePosixPath,
) -> None:
    parent_fd = _open_or_create_parent_fd(skills_root, relative_parent)
    if parent_fd is None:
        raise RuntimeError("secure dir_fd publication is unavailable")

    temp_name = ""
    temp_fd = -1
    cleanup_path: Path | None = None
    try:
        temp_name, temp_fd = _create_temp_directory_at(parent_fd, target.name)
        cleanup_path = _descriptor_real_path(temp_fd)
        write_path = cleanup_path if sys.platform == "darwin" else _descriptor_path(temp_fd)
        _write_package_tree(write_path, files)
        parse_skill_package(write_path / "SKILL.md", skill_id, write_path)
        try:
            os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(f"skill already exists: {skill_id}")
        os.replace(
            temp_name,
            target.name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        temp_name = ""
    finally:
        if temp_name and temp_fd >= 0:
            if cleanup_path is not None:
                shutil.rmtree(cleanup_path, ignore_errors=True)
            else:
                try:
                    os.rmdir(temp_name, dir_fd=parent_fd)
                except OSError as exc:
                    logger.warning("Failed to remove temporary skill directory %s: %s", temp_name, exc)
        if temp_fd >= 0:
            os.close(temp_fd)
        os.close(parent_fd)


def _atomic_write_package_path(
    target: Path,
    files: Mapping[str, tuple[str, bytes]],
    skill_id: str,
    *,
    skills_root: Path,
    relative_parent: PurePosixPath,
) -> None:
    _reject_symlink_components(skills_root, relative_parent)
    target.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(skills_root, relative_parent)
    temp_path = Path(tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=target.parent))
    try:
        _write_package_tree(temp_path, files)
        parse_skill_package(temp_path / "SKILL.md", skill_id, temp_path)
        _reject_symlink_components(skills_root, relative_parent)
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"skill already exists: {skill_id}")
        os.replace(temp_path, target)
    finally:
        if temp_path.exists() or temp_path.is_symlink():
            shutil.rmtree(temp_path, ignore_errors=True)


def atomic_write_package(
    target: Path,
    files: Mapping[str, tuple[str, bytes]],
    skill_id: str,
    *,
    skills_root: Path,
) -> None:
    relative_parent = PurePosixPath(target.parent.relative_to(skills_root).as_posix())

    with _exclusive_creation_lock(skills_root, skill_id):
        if skills_root.is_symlink():
            raise ValueError("skills root must not be a symlink")
        _reject_symlink_components(skills_root, relative_parent)
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"skill already exists: {skill_id}")

        if _supports_secure_dir_fd_publication():
            _atomic_write_package_dir_fd(
                target,
                files,
                skill_id,
                skills_root=skills_root,
                relative_parent=relative_parent,
            )
        else:
            _atomic_write_package_path(
                target,
                files,
                skill_id,
                skills_root=skills_root,
                relative_parent=relative_parent,
            )


def create_skill(
    skill_id: str,
    skill_md: str,
    additional_files: Mapping[str, str] | None = None,
    *,
    root: Path | None = None,
) -> dict:
    validated_id = validate_skill_id(skill_id)
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
    _reject_symlink_components(skills_root, relative)
    skill = parse_skill_package(target / "SKILL.md", validated_id, target)
    return {"created": True, "skill": skill.summary(), "files": sorted(files)}


def install_builtin_skills(*, root: Path | None = None, source_root: Path | None = None) -> list[str]:
    skills_root = Path(root or get_skills_root()).expanduser()
    builtin_root = Path(source_root or BUILTIN_SKILLS_ROOT)
    if not builtin_root.is_dir():
        return []

    installed: list[str] = []
    for source in sorted(path for path in builtin_root.iterdir() if path.is_dir()):
        skill_file = source / "SKILL.md"
        if not skill_file.is_file():
            continue
        skill_id = f"gate/{source.name}"
        additional = {}
        try:
            for path in source.rglob("*"):
                if not path.is_file() or path.name == "SKILL.md":
                    continue
                if path.stat().st_size > MAX_FILE_BYTES:
                    raise ValueError(f"builtin skill file exceeds size limit: {path}")
                additional[path.relative_to(source).as_posix()] = path.read_text(
                    encoding="utf-8"
                )
            skill_text = skill_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, ValueError):
            logger.exception("Failed to read builtin skill %s", skill_id)
            continue
        try:
            create_skill(
                skill_id,
                skill_text,
                additional,
                root=skills_root,
            )
        except FileExistsError:
            continue
        except Exception:
            logger.exception("Failed to install builtin skill %s", skill_id)
            continue
        installed.append(skill_id)
    return installed
