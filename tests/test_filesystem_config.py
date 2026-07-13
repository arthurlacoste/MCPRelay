import os
from pathlib import Path

from filesystem_config import get_filesystem_roots


def test_filesystem_roots_default_to_volume_root():
    base_dir = Path('/project')

    assert get_filesystem_roots(base_dir, {}) == ['/']


def test_filesystem_roots_support_multiple_directories():
    raw_roots = os.pathsep.join(['/workspace/one', '/workspace/two'])

    assert get_filesystem_roots(
        Path('/project'),
        {'MCP_FILESYSTEM_ROOTS': raw_roots},
    ) == ['/workspace/one', '/workspace/two']


def test_filesystem_roots_ignore_empty_values():
    raw_roots = os.pathsep.join(['/workspace/one', '', '/workspace/two'])

    assert get_filesystem_roots(
        Path('/project'),
        {'MCP_FILESYSTEM_ROOTS': raw_roots},
    ) == ['/workspace/one', '/workspace/two']
