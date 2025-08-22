"""
Google Drive status tracking class.

This module provides a thin wrapper around the ``BaseStatus`` class
defined in ``status/__init__.py``.  It is used to represent the
state of a Google Drive download or upload.  The original
mirror‑leech project contained a much richer implementation that
reported detailed metrics via a web UI; this simplified version only
stores basic progress information and a reference to the listener
object.
"""

from __future__ import annotations

from typing import Optional, Any

from . import BaseStatus


class GdriveStatus(BaseStatus):
    """Status information for Google Drive transfers."""

    def __init__(self, listener: Any, gid: Optional[str] = None, queued: bool = False) -> None:
        super().__init__(listener, gid, queued)

    def update(self) -> None:
        """Update the progress counters.

        In a full implementation this method would poll the Google
        Drive API for the current progress of the transfer and update
        ``self.progress``, ``self.speed`` and ``self.size`` accordingly.
        For now it simply leaves those values unchanged.
        """
        return


__all__ = ["GdriveStatus"]