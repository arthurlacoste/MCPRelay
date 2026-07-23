from gate_cli.versioning import is_stable_tag, select_latest_stable_tag


def test_latest_stable_tag_ignores_prereleases_and_non_semver_tags():
    tags = ["v0.9.0", "v1.0.0-beta.1", "notes", "v1.2.0", "v1.1.9"]

    assert select_latest_stable_tag(tags) == "v1.2.0"
    assert is_stable_tag("v1.2.0")
    assert not is_stable_tag("v1.2.0-rc.1")


def test_normalize_and_classify_prerelease_tags():
    from gate_cli.versioning import is_prerelease_tag, is_semver_tag, normalize_tag

    assert normalize_tag("0.1.14-beta.1") == "v0.1.14-beta.1"
    assert normalize_tag("v0.1.14") == "v0.1.14"
    assert is_semver_tag("v0.1.14-beta.1")
    assert is_prerelease_tag("v0.1.14-beta.1")
    assert not is_prerelease_tag("v0.1.14")


def test_normalize_rejects_invalid_version():
    from gate_cli.versioning import normalize_tag

    try:
        normalize_tag("latest")
    except ValueError as error:
        assert "Invalid Gate version" in str(error)
    else:
        raise AssertionError("invalid version accepted")


def test_build_metadata_is_rejected():
    from gate_cli.versioning import is_semver_tag, normalize_tag

    assert not is_semver_tag("v1.2.3+build.1")
    try:
        normalize_tag("1.2.3+build.1")
    except ValueError as error:
        assert "Invalid Gate version" in str(error)
    else:
        raise AssertionError("build metadata accepted")
