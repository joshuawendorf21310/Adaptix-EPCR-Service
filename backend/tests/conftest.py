"""Pytest bootstrap configuration for the EPCR backend test suite.

Ensures test collection has a real async database URL available without
weakening production startup enforcement. The test database lives in the
system temp directory so the repository working tree stays clean.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


_DEFAULT_DB_NAME = "adaptix_epcr_service_pytest.db"


def _shared_sqlite_test_database_path() -> Path:
    """Return the shared SQLite database path used by backend tests."""
    return Path(tempfile.gettempdir()) / _DEFAULT_DB_NAME


def _per_process_sqlite_test_database_path() -> Path:
    """Return a per-process SQLite path used as a fallback when the shared
    file is locked by another active test run (common on Windows)."""
    return Path(tempfile.gettempdir()) / f"adaptix_epcr_service_pytest_{os.getpid()}.db"


def _sqlite_test_database_url(path: Path | None = None) -> str:
    """Build a deterministic SQLite URL for local and CI test runs."""
    database_path = path or _shared_sqlite_test_database_path()
    return f"sqlite+aiosqlite:///{database_path.as_posix()}"


def _ensure_clean_default_sqlite_database() -> None:
    """Reset the default SQLite test database so schema drift cannot persist.

    On Windows the shared DB file can be locked by another lingering test
    process; in that case fall back to a per-process file so collection
    still proceeds rather than aborting the entire suite.
    """
    default_url = _sqlite_test_database_url()
    configured_url = os.environ.get("EPCR_DATABASE_URL")
    if configured_url and configured_url != default_url:
        return

    database_path = _shared_sqlite_test_database_path()
    sidecars = (
        database_path,
        database_path.with_name(f"{database_path.name}-shm"),
        database_path.with_name(f"{database_path.name}-wal"),
    )
    locked = False
    for path in sidecars:
        if not path.exists():
            continue
        try:
            path.unlink()
        except PermissionError:
            # Shared file held by another active process — fall through to
            # a per-process DB so this run isn't blocked.
            locked = True
            break

    if locked:
        fallback = _per_process_sqlite_test_database_path()
        fallback_sidecars = (
            fallback,
            fallback.with_name(f"{fallback.name}-shm"),
            fallback.with_name(f"{fallback.name}-wal"),
        )
        for path in fallback_sidecars:
            if path.exists():
                try:
                    path.unlink()
                except PermissionError:
                    # Even the per-process file is locked; let the engine
                    # reopen it — tests are idempotent w.r.t. schema.
                    pass
        os.environ["EPCR_DATABASE_URL"] = _sqlite_test_database_url(fallback)
        return

    os.environ["EPCR_DATABASE_URL"] = default_url


_ensure_clean_default_sqlite_database()