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
