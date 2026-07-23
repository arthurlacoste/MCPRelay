import json
from pathlib import Path

from gate_cli.remote import GitHubRepository


class Response:
    def __init__(self, payload: bytes):
        self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_): return None
    def read(self): return self.payload


def test_latest_stable_release_uses_release_assets():
    payload = json.dumps({
        "tag_name": "v0.2.0",
        "prerelease": False,
        "draft": False,
        "assets": [
            {"name": "gate-v0.2.0.tar.gz", "browser_download_url": "https://example/archive"},
            {"name": "SHA256SUMS", "browser_download_url": "https://example/checksums"},
        ],
    }).encode()
    repo = GitHubRepository(opener=lambda request: Response(payload))

    release = repo.latest_stable_release()

    assert release.tag == "v0.2.0"
    assert release.archive_url == "https://example/archive"
    assert release.checksums_url == "https://example/checksums"


def test_release_requires_archive_and_checksums_assets():
    payload = json.dumps({"tag_name": "v0.2.0", "prerelease": False, "draft": False, "assets": []}).encode()
    repo = GitHubRepository(opener=lambda request: Response(payload))

    try:
        repo.latest_stable_release()
    except RuntimeError as error:
        assert "required assets" in str(error)
    else:
        raise AssertionError("release without assets accepted")


def test_release_by_tag_accepts_unprefixed_prerelease():
    import io
    import json
    from gate_cli.remote import GitHubRepository

    payload = {
        "tag_name": "v0.1.14-beta.1",
        "assets": [
            {"name": "gate-v0.1.14-beta.1.tar.gz", "browser_download_url": "https://example/archive"},
            {"name": "SHA256SUMS", "browser_download_url": "https://example/sums"},
        ],
    }
    seen = []

    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): return False

    def opener(request):
        seen.append(request.full_url)
        return Response(json.dumps(payload).encode())

    release = GitHubRepository(opener=opener).release_by_tag("0.1.14-beta.1")

    assert release.tag == "v0.1.14-beta.1"
    assert seen[0].endswith("/releases/tags/v0.1.14-beta.1")


def test_release_by_tag_rejects_missing_assets():
    import io
    import json
    import pytest
    from gate_cli.remote import GitHubRepository

    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): return False

    repository = GitHubRepository(opener=lambda request: Response(json.dumps({"tag_name": "v0.1.14-beta.1", "assets": []}).encode()))

    with pytest.raises(RuntimeError, match="missing required assets"):
        repository.release_by_tag("v0.1.14-beta.1")
