"""Pytest bootstrap configuration for the EPCR backend test suite.

Ensures test collection has a real async database URL available without
weakening production startup enforcement. The test database lives in the
system temp directory so the repository working tree stays clean.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _sqlite_test_database_url() -> str:
    """Build a deterministic SQLite URL for local and CI test runs."""
    database_path = Path(tempfile.gettempdir()) / "adaptix_epcr_service_pytest.db"
    return f"sqlite+aiosqlite:///{database_path.as_posix()}"


os.environ.setdefault("EPCR_DATABASE_URL", _sqlite_test_database_url())