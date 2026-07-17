import json
from pathlib import Path

from gate_cli.remote import GitHubRepository


class Response:
    def __init__(self, payload: bytes):
        self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_): return None
    def read(self): return self.payload


def test_repository_selects_latest_stable_tag():
    payload = json.dumps([{"name": "v1.0.0"}, {"name": "v1.2.0-beta.1"}, {"name": "v1.1.0"}]).encode()
    repo = GitHubRepository(opener=lambda request: Response(payload))

    assert repo.latest_stable_tag() == "v1.1.0"


def test_repository_resolves_edge_sha():
    payload = json.dumps({"sha": "abcdef1234567890"}).encode()
    repo = GitHubRepository(opener=lambda request: Response(payload))

    assert repo.latest_edge_sha() == "abcdef1234567890"
    assert repo.edge_version("0.1.0", "abcdef1234567890") == "0.1.0-edge+abcdef1"
