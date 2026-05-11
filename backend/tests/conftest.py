"""Pytest bootstrap configuration for the EPCR backend test suite.

Ensures test collection has a real async database URL available without
weakening production startup enforcement. The test database lives in the
system temp directory so the repository working tree stays clean.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _sqlite_test_database_path() -> Path:
    """Return the shared SQLite database path used by backend tests."""
    return Path(tempfile.gettempdir()) / "adaptix_epcr_service_pytest.db"


def _sqlite_test_database_url() -> str:
    """Build a deterministic SQLite URL for local and CI test runs."""
    database_path = _sqlite_test_database_path()
    return f"sqlite+aiosqlite:///{database_path.as_posix()}"


def _ensure_clean_default_sqlite_database() -> None:
    """Reset the default SQLite test database so schema drift cannot persist."""
    default_url = _sqlite_test_database_url()
    configured_url = os.environ.get("EPCR_DATABASE_URL")
    if configured_url and configured_url != default_url:
        return

    database_path = _sqlite_test_database_path()
    sidecars = (
        database_path,
        database_path.with_name(f"{database_path.name}-shm"),
        database_path.with_name(f"{database_path.name}-wal"),
    )
    for path in sidecars:
        if path.exists():
            path.unlink()

    os.environ["EPCR_DATABASE_URL"] = default_url


_ensure_clean_default_sqlite_database()