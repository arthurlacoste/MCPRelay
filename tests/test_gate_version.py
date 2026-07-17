from gate_cli.versioning import is_stable_tag, select_latest_stable_tag


def test_latest_stable_tag_ignores_prereleases_and_non_semver_tags():
    tags = ["v0.9.0", "v1.0.0-beta.1", "notes", "v1.2.0", "v1.1.9"]

    assert select_latest_stable_tag(tags) == "v1.2.0"
    assert is_stable_tag("v1.2.0")
    assert not is_stable_tag("v1.2.0-rc.1")
