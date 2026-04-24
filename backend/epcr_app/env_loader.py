"""Local environment loader for the ePCR service.

Loads repository and backend ``.env`` files without overriding real process
environment values. This keeps local development runnable while preserving
production precedence rules.
"""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a simple ``.env`` file into key/value pairs.

    Args:
        path: Environment file path.

    Returns:
        Parsed environment mapping.
    """

    parsed: dict[str, str] = {}
    if not path.exists():
        return parsed

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip().strip('"').strip("'")
    return parsed


@lru_cache(maxsize=1)
def load_local_env() -> None:
    """Load local ``.env`` files once with process-env precedence.

    Returns:
        None.
    """

    backend_root = Path(__file__).resolve().parents[1]
    repo_root = backend_root.parent

    merged: dict[str, str] = {}
    for candidate in (repo_root / ".env", backend_root / ".env"):
        merged.update(_parse_env_file(candidate))

    for key, value in merged.items():
        os.environ.setdefault(key, value)