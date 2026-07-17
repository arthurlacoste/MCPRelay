import hashlib
from pathlib import Path

import pytest

from gate_cli.integrity import checksum_for_tag, verify_sha256


def test_checksum_manifest_selects_exact_tag():
    manifest = "# Gate release archives\nabc123  gate-v0.1.0.tar.gz\ndef456  gate-v0.2.0.tar.gz\n"
    assert checksum_for_tag(manifest, "v0.2.0") == "def456"


def test_checksum_manifest_requires_tag():
    with pytest.raises(RuntimeError, match="No SHA256"):
        checksum_for_tag("abc123  gate-v0.1.0.tar.gz\n", "v0.2.0")


def test_verify_sha256_rejects_modified_archive(tmp_path):
    archive = tmp_path / "v0.2.0.tar.gz"
    archive.write_bytes(b"archive")
    expected = hashlib.sha256(b"archive").hexdigest()
    verify_sha256(archive, expected)
    archive.write_bytes(b"modified")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        verify_sha256(archive, expected)
