from __future__ import annotations

from pathlib import Path

import pytest

from skill_catalog import skills_read, skills_search
from skill_writer import (
    MAX_FILE_COUNT,
    MAX_PACKAGE_BYTES,
    create_skill,
    install_builtin_skills,
)

VALID_SKILL = "---\nname: Deploy Vercel\ndescription: Deploy a project safely.\n---\n\nSteps.\n"


def test_simple_skill_creation_is_visible_and_readable(tmp_path):
    result = create_skill("deploy/vercel", VALID_SKILL, root=tmp_path)

    assert result == {
        "created": True,
        "skill": {
            "id": "deploy/vercel",
            "name": "Deploy Vercel",
            "description": "Deploy a project safely.",
        },
        "files": ["SKILL.md"],
    }
    assert skills_search("vercel", root=tmp_path)["matches"][0]["id"] == "deploy/vercel"
    assert skills_read("deploy/vercel", root=tmp_path)["content"] == VALID_SKILL


def test_nested_package_creation(tmp_path):
    result = create_skill(
        "deploy/vercel",
        VALID_SKILL,
        {
            "references/cli.md": "Use the CLI.\n",
            "scripts/check.sh": "#!/bin/sh\necho check\n",
        },
        root=tmp_path,
    )

    assert result["files"] == ["SKILL.md", "references/cli.md", "scripts/check.sh"]
    assert skills_read("deploy/vercel", "references/cli.md", root=tmp_path)["content"] == "Use the CLI.\n"


@pytest.mark.parametrize("skill_md", ["", "   ", None])
def test_missing_or_empty_skill_md_is_rejected(tmp_path, skill_md):
    with pytest.raises((TypeError, ValueError), match="skill_md"):
        create_skill("example", skill_md, root=tmp_path)
    assert not (tmp_path / "example").exists()


def test_invalid_frontmatter_is_rejected_without_publication(tmp_path):
    with pytest.raises(ValueError, match="frontmatter"):
        create_skill("example", "---\nname: Broken\n---\n", root=tmp_path)
    assert not (tmp_path / "example").exists()


@pytest.mark.parametrize("skill_id", [
    "../example", "/example", "nested\\example", "nested//example", "./example", "example/.", "",
])
def test_invalid_skill_ids_are_rejected(tmp_path, skill_id):
    with pytest.raises(ValueError, match="skill_id"):
        create_skill(skill_id, VALID_SKILL, root=tmp_path)


@pytest.mark.parametrize("path", [
    "../outside.txt", "/tmp/outside.txt", "nested\\file.txt", "nested//file.txt",
    "./file.txt", "folder/../file.txt", "", ".", "SKILL.md",
])
def test_invalid_additional_paths_are_rejected(tmp_path, path):
    with pytest.raises(ValueError, match="path|SKILL.md"):
        create_skill("example", VALID_SKILL, {path: "content"}, root=tmp_path)
    assert not (tmp_path / "example").exists()


@pytest.mark.parametrize("content", [b"binary", "abc\x00def", "abc\x01def", "abc\x7fdef"])
def test_binary_or_non_text_payloads_are_rejected(tmp_path, content):
    with pytest.raises((TypeError, ValueError), match="text|binary"):
        create_skill("example", VALID_SKILL, {"data.bin": content}, root=tmp_path)


def test_file_count_limit(tmp_path):
    files = {f"refs/{index}.txt": "x" for index in range(MAX_FILE_COUNT)}
    with pytest.raises(ValueError, match="files"):
        create_skill("example", VALID_SKILL, files, root=tmp_path)


def test_per_file_and_package_size_limits(tmp_path):
    with pytest.raises(ValueError, match="file exceeds"):
        create_skill("large", VALID_SKILL, {"large.txt": "x" * (256 * 1024 + 1)}, root=tmp_path)

    files = {f"refs/{index}.txt": "x" * 65536 for index in range(16)}
    with pytest.raises(ValueError, match="package exceeds"):
        create_skill("package", VALID_SKILL, files, root=tmp_path)
    assert sum(len(value.encode()) for value in files.values()) >= MAX_PACKAGE_BYTES


def test_existing_target_is_never_overwritten(tmp_path):
    first = create_skill("example", VALID_SKILL, root=tmp_path)
    original = (tmp_path / "example/SKILL.md").read_text()

    with pytest.raises(FileExistsError, match="already exists"):
        create_skill("example", VALID_SKILL.replace("Deploy", "Replace"), root=tmp_path)

    assert first["created"] is True
    assert (tmp_path / "example/SKILL.md").read_text() == original


def test_symlink_target_and_symlinked_parent_are_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "skills"
    root.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        create_skill("linked/example", VALID_SKILL, root=root)
    assert not (outside / "example").exists()

    target = root / "target"
    target.symlink_to(outside, target_is_directory=True)
    with pytest.raises((FileExistsError, ValueError), match="symlink|exists"):
        create_skill("target", VALID_SKILL, root=root)


def test_validation_failure_leaves_no_destination_or_temp_directory(tmp_path):
    with pytest.raises(ValueError):
        create_skill("nested/example", "invalid", {"refs/a.txt": "ok"}, root=tmp_path)

    assert not (tmp_path / "nested/example").exists()
    assert list(tmp_path.rglob(".example.tmp-*")) == []


def test_publish_failure_cleans_temp_directory(tmp_path, monkeypatch):
    import skill_writer

    real_replace = skill_writer.os.replace

    def fail_replace(src, dst, **kwargs):
        if str(src).startswith(".example.tmp-"):
            raise OSError("publish failed")
        return real_replace(src, dst, **kwargs)

    monkeypatch.setattr(skill_writer.os, "replace", fail_replace)

    with pytest.raises(OSError, match="publish failed"):
        create_skill("example", VALID_SKILL, root=tmp_path)

    assert not (tmp_path / "example").exists()
    assert list(tmp_path.glob(".example.tmp-*")) == []


def test_builtin_skill_is_installed_but_user_copy_is_preserved(tmp_path):
    source = tmp_path / "source"
    builtin = source / "skill-creator"
    builtin.mkdir(parents=True)
    (builtin / "SKILL.md").write_text(
        "---\nname: Skill Creator\ndescription: Create reusable skills.\n---\nBuiltin\n",
        encoding="utf-8",
    )
    root = tmp_path / "skills"

    installed = install_builtin_skills(root=root, source_root=source)
    assert installed == ["gate/skill-creator"]
    user_file = root / "gate/skill-creator/SKILL.md"
    user_file.write_text(user_file.read_text() + "User edit\n", encoding="utf-8")

    assert install_builtin_skills(root=root, source_root=source) == []
    assert user_file.read_text().endswith("User edit\n")


def test_symlink_swap_before_temp_creation_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    root.mkdir()
    namespace = root / "nested"
    namespace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    import skill_writer

    real_mkdtemp = skill_writer.tempfile.mkdtemp

    def swap_then_create(*args, **kwargs):
        namespace.rename(root / "nested-original")
        namespace.symlink_to(outside, target_is_directory=True)
        return real_mkdtemp(*args, **kwargs)

    monkeypatch.setattr(skill_writer.tempfile, "mkdtemp", swap_then_create)

    with pytest.raises(ValueError, match="symlink|parent changed"):
        create_skill("nested/example", VALID_SKILL, root=root)
    assert not (outside / "example").exists()


def test_symlink_swap_before_publish_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    root.mkdir()
    namespace = root / "nested"
    namespace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    import skill_writer

    real_parse = skill_writer.parse_skill_package

    def swap_after_validation(*args, **kwargs):
        result = real_parse(*args, **kwargs)
        namespace.rename(root / "nested-original")
        namespace.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(skill_writer, "parse_skill_package", swap_after_validation)

    with pytest.raises(ValueError, match="symlink"):
        create_skill("nested/example", VALID_SKILL, root=root)
    assert not (outside / "example").exists()



def test_concurrent_creation_never_overwrites_first_package(tmp_path, monkeypatch):
    import threading
    import skill_writer

    first_entered_parse = threading.Event()
    allow_first_to_finish = threading.Event()
    real_parse = skill_writer.parse_skill_package
    parse_calls = 0

    def pause_first_parse(*args, **kwargs):
        nonlocal parse_calls
        parse_calls += 1
        if parse_calls == 1:
            first_entered_parse.set()
            assert allow_first_to_finish.wait(timeout=5)
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(skill_writer, "parse_skill_package", pause_first_parse)
    errors: list[Exception] = []

    def create_first():
        create_skill("same", VALID_SKILL, {"owner.txt": "first"}, root=tmp_path)

    first = threading.Thread(target=create_first)
    first.start()
    assert first_entered_parse.wait(timeout=5)

    try:
        create_skill("same", VALID_SKILL, {"owner.txt": "second"}, root=tmp_path)
    except Exception as exc:
        errors.append(exc)
    finally:
        allow_first_to_finish.set()
        first.join(timeout=5)

    assert not first.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], FileExistsError)
    assert (tmp_path / "same/owner.txt").read_text() == "first"
    assert list(tmp_path.glob(".create-*.lock")) == []



def test_stale_creation_lock_is_recovered(tmp_path, monkeypatch):
    import hashlib
    import json
    import skill_writer

    skill_id = "stale/example"
    lock_name = hashlib.sha256(skill_id.encode("utf-8")).hexdigest()
    lock_path = tmp_path / f".create-{lock_name}.lock"
    lock_path.write_text(json.dumps({"pid": 999999999, "created": 0}), encoding="ascii")

    result = create_skill(skill_id, VALID_SKILL, root=tmp_path)

    assert result["created"] is True
    assert not lock_path.exists()


def test_live_creation_lock_is_preserved(tmp_path):
    import hashlib
    import json
    import os
    import time

    skill_id = "live/example"
    lock_name = hashlib.sha256(skill_id.encode("utf-8")).hexdigest()
    lock_path = tmp_path / f".create-{lock_name}.lock"
    lock_path.write_text(json.dumps({"pid": os.getpid(), "created": time.time()}), encoding="ascii")

    with pytest.raises(FileExistsError, match="in progress"):
        create_skill(skill_id, VALID_SKILL, root=tmp_path)
    assert lock_path.exists()


def test_invalid_unicode_is_rejected_as_value_error(tmp_path):
    with pytest.raises(ValueError, match="Unicode"):
        create_skill("unicode", VALID_SKILL, {"bad.txt": "\ud800"}, root=tmp_path)


def test_broken_builtin_does_not_block_following_builtin(tmp_path):
    source = tmp_path / "source"
    broken = source / "a-broken"
    valid = source / "b-valid"
    broken.mkdir(parents=True)
    valid.mkdir(parents=True)
    (broken / "SKILL.md").write_text("invalid", encoding="utf-8")
    (valid / "SKILL.md").write_text(
        "---\nname: Valid\ndescription: Still installed.\n---\nBody\n",
        encoding="utf-8",
    )

    installed = install_builtin_skills(root=tmp_path / "skills", source_root=source)

    assert installed == ["gate/b-valid"]
    assert (tmp_path / "skills/gate/b-valid/SKILL.md").is_file()



def test_stale_lock_retry_race_preserves_file_exists_error(tmp_path, monkeypatch):
    import skill_writer

    real_open = skill_writer.os.open
    attempts = 0

    def race_open(path, flags, mode=0o777):
        nonlocal attempts
        if str(path).endswith(".lock"):
            attempts += 1
            raise FileExistsError("raced")
        return real_open(path, flags, mode)

    monkeypatch.setattr(skill_writer, "_remove_stale_lock", lambda path: True)
    monkeypatch.setattr(skill_writer.os, "open", race_open)

    with pytest.raises(FileExistsError, match="in progress"):
        create_skill("race/example", VALID_SKILL, root=tmp_path)
    assert attempts == 2


def test_publish_fails_closed_without_dir_fd_support(tmp_path, monkeypatch):
    import skill_writer

    monkeypatch.setattr(skill_writer, "_open_or_create_parent_fd", lambda root, relative: None)

    with pytest.raises(RuntimeError, match="dir_fd"):
        create_skill("example", VALID_SKILL, root=tmp_path)
    assert not (tmp_path / "example").exists()
    assert list(tmp_path.glob(".example.tmp-*")) == []



def test_losing_lock_contender_never_deletes_winner_lock(tmp_path, monkeypatch):
    import hashlib
    import json
    import os
    import time
    import skill_writer

    skill_id = "winner/example"
    lock_name = hashlib.sha256(skill_id.encode("utf-8")).hexdigest()
    lock_path = tmp_path / f".create-{lock_name}.lock"
    lock_path.write_text(json.dumps({"pid": os.getpid(), "created": time.time()}), encoding="ascii")

    with pytest.raises(FileExistsError, match="in progress"):
        with skill_writer._exclusive_creation_lock(tmp_path, skill_id):
            pass

    assert lock_path.exists()


def test_permission_error_lock_uses_mtime_staleness(tmp_path, monkeypatch):
    import hashlib
    import json
    import os
    import skill_writer

    skill_id = "permission/example"
    lock_name = hashlib.sha256(skill_id.encode("utf-8")).hexdigest()
    lock_path = tmp_path / f".create-{lock_name}.lock"
    lock_path.write_text(json.dumps({"pid": 1, "created": 0}), encoding="ascii")
    old = skill_writer.time.time() - skill_writer.LOCK_STALE_SECONDS - 1
    os.utime(lock_path, (old, old))
    monkeypatch.setattr(skill_writer.os, "kill", lambda pid, signal: (_ for _ in ()).throw(PermissionError()))

    assert skill_writer._remove_stale_lock(lock_path) is True
    assert not lock_path.exists()


def test_oversized_builtin_file_is_skipped_without_reading(tmp_path, monkeypatch):
    import skill_writer

    source = tmp_path / "source"
    builtin = source / "large"
    builtin.mkdir(parents=True)
    (builtin / "SKILL.md").write_text(
        "---\nname: Large\ndescription: Oversized reference.\n---\nBody\n",
        encoding="utf-8",
    )
    reference = builtin / "reference.txt"
    reference.write_text("x", encoding="utf-8")

    real_stat = Path.stat

    def oversized_stat(self, *args, **kwargs):
        result = real_stat(self, *args, **kwargs)
        if self == reference:
            class StatProxy:
                def __init__(self, original):
                    self._original = original
                    self.st_size = skill_writer.MAX_FILE_BYTES + 1

                def __getattr__(self, name):
                    return getattr(self._original, name)

            return StatProxy(result)
        return result

    monkeypatch.setattr(Path, "stat", oversized_stat)

    assert install_builtin_skills(root=tmp_path / "skills", source_root=source) == []
    assert not (tmp_path / "skills/gate/large").exists()
