from __future__ import annotations

import hashlib
from pathlib import Path


def checksum_for_tag(manifest: str, tag: str) -> str:
    expected_name = f"gate-{tag}.tar.gz"
    for raw in manifest.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[-1] == expected_name:
            return parts[0]
    raise RuntimeError(f"No SHA256 checksum published for {tag}.")


def verify_sha256(path: Path, expected: str) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual.lower() != expected.lower():
        raise RuntimeError(f"Gate archive checksum mismatch: expected {expected}, got {actual}.")
