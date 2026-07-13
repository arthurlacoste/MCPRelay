import os
from collections.abc import Mapping
from pathlib import Path


def get_filesystem_roots(
    base_dir: Path,
    environ: Mapping[str, str] | None = None,
) -> list[str]:
    env = os.environ if environ is None else environ
    raw_roots = env.get('MCP_FILESYSTEM_ROOTS', '').strip()
    default_root = str(Path(base_dir.anchor))

    if not raw_roots:
        return [default_root]

    roots = [root.strip() for root in raw_roots.split(os.pathsep) if root.strip()]
    if not roots:
        return [default_root]

    return [str(Path(root).expanduser()) for root in roots]
