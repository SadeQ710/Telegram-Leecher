"""
Lightweight configuration manager.

The original mirror‑leech project includes a sophisticated configuration
manager capable of reading settings from environment variables and
persisting changes back to a database.  This simplified version
provides basic access to environment variables via attribute lookup
along with a small helper for retrieving all values at once.
"""

from __future__ import annotations

import os
from typing import Dict, Any


class Config:
    """Wrapper around os.environ that provides attribute style access."""
    def __getattr__(self, item: str) -> str | None:
        return os.environ.get(item)

    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        """Return a configuration value or a default if missing."""
        return os.environ.get(key, default)

    @staticmethod
    def get_all() -> Dict[str, str]:
        """Return a copy of all environment variables for inspection."""
        return dict(os.environ)

    @staticmethod
    def set(key: str, value: str) -> None:
        """Set an environment variable at runtime.  Note that changes are
        not persisted across restarts."""
        os.environ[key] = value


__all__ = ["Config"]