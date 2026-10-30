"""Resolve a URL path to a file under a static root.

`root / path` is not containment: pathlib discards `root` when `path` is
absolute, and the ASGI server has already decoded `%2f`, so `//etc/passwd` and
`/%2fetc%2fpasswd` both reach a catch-all route as `/etc/passwd`. `..` escapes
the same join. The check has to run on the resolved path.
"""

from pathlib import Path
from typing import Optional


def resolve_static_file(root: Path, path: str) -> Optional[Path]:
    """Return the file `path` names under `root`, or None if there is no such file.

    Symlinks are followed before the containment check, so a link out of
    `root` is refused too.
    """
    resolved_root = root.resolve()
    try:
        candidate = (resolved_root / path).resolve()
        if candidate.is_relative_to(resolved_root) and candidate.is_file():
            return candidate
    except (OSError, RuntimeError, ValueError):
        # NUL byte, over-long name, symlink loop: none of these name a file.
        pass
    return None
