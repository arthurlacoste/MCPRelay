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
    real_replace = Path.replace

    def fail_replace(self, target):
        if self.name.startswith(".example.tmp-"):
            raise OSError("publish failed")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_replace)
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
