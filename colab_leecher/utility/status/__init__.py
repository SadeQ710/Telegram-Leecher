"""
Minimal status tracking classes used throughout the downloader.

These classes are simplified stand‑ins for the much more complex
status objects found in the original mirror‑leech bot.  They are
designed to be lightweight and to satisfy the attribute lookups
performed elsewhere in this project.  If you need richer status
information (for example to report progress through a web interface)
then you should replace these implementations with more complete
versions.
"""

from __future__ import annotations

from typing import Any, Optional


class BaseStatus:
    """Base class for status objects.  Stores a listener and optional id."""
    def __init__(self, listener: Any, gid: Optional[str] = None, queued: bool = False) -> None:
        self.listener = listener
        self._gid = gid or ""
        self.queued = queued
        self.progress = 0.0
        self.speed = 0.0
        self.size = 0
        self.name = getattr(listener, "name", "")

    def update(self) -> None:
        """Placeholder update method.  Real implementations should update
        internal counters based on download state."""
        pass

    def gid(self) -> str:
        return self._gid


class QueueStatus(BaseStatus):
    """Status for queued tasks."""
    pass


class YtDlpStatus(BaseStatus):
    """Status for yt‑dlp downloads.  Stores a reference to the helper."""
    def __init__(self, listener: Any, helper: Any, gid: Optional[str] = None) -> None:
        super().__init__(listener, gid)
        self.helper = helper


class SabnzbdStatus(BaseStatus):
    """Status for SABnzbd downloads."""
    pass


class Aria2Status(BaseStatus):
    """Status for Aria2c downloads."""
    pass


class NzbStatus(BaseStatus):
    """Alias for SabnzbdStatus for backwards compatibility."""
    pass


class GdriveStatus(BaseStatus):
    """Status for Google Drive downloads."""
    pass


class DirectStatus(BaseStatus):
    """Status for direct downloads."""
    pass

# Import additional per‑service status classes defined in sibling modules
try:
    from .gdrive_status import GdriveStatus as GDriveStatus  # noqa: F401
except Exception:
    # If the module cannot be imported, fall back to the generic class
    GDriveStatus = GdriveStatus = Gdrive_status = BaseStatus  # type: ignore
try:
    from .nzb_status import NzbStatus as NZBStatus  # noqa: F401
except Exception:
    NZBStatus = BaseStatus  # type: ignore


__all__ = [
    "BaseStatus",
    "QueueStatus",
    "YtDlpStatus",
    "SabnzbdStatus",
    "Aria2Status",
    "NzbStatus",
    "GdriveStatus",
    "DirectStatus",
    "GDriveStatus",
    "NZBStatus",
]