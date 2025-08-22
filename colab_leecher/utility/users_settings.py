"""
Simplified per‑user settings module.

The mirror‑leech bot supports customisation on a per‑user basis via
database stored preferences.  For the sake of simplicity this
implementation exposes a basic in memory mapping of user IDs to
preferences.  In a production environment you may wish to back this
store with a database and provide commands to modify it at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class UserSettings:
    """Container for individual user preferences."""
    # Add user specific attributes here, e.g. preferred upload method
    upload_method: str = "rc"
    # Additional user settings can be defined here


class UsersSettingsStore:
    """In memory store for user settings."""
    def __init__(self) -> None:
        self._store: Dict[int, UserSettings] = {}

    def get(self, user_id: int) -> UserSettings:
        return self._store.setdefault(user_id, UserSettings())

    def set(self, user_id: int, settings: UserSettings) -> None:
        self._store[user_id] = settings


# Create a single global store instance
user_settings_store = UsersSettingsStore()

__all__ = ["UserSettings", "UsersSettingsStore", "user_settings_store"]