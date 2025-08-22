"""
NZB download status tracking class.

This module defines a simple status class for NZB downloads handled
via SABnzbd.  The original mirror‑leech project implemented a
detailed status reader that queried the SABnzbd API for real time
information.  To minimise complexity this reimplementation inherits
from ``BaseStatus`` and leaves the update logic as a stub.
"""

from __future__ import annotations

from typing import Optional, Any

from . import BaseStatus


class NzbStatus(BaseStatus):
    """Status information for NZB (SABnzbd) downloads."""

    def __init__(self, listener: Any, gid: Optional[str] = None, queued: bool = False) -> None:
        super().__init__(listener, gid, queued)

    def update(self) -> None:
        """Update NZB progress counters.

        A full implementation would call the SABnzbd API and update the
        attributes of this instance.  This placeholder leaves the
        counters unchanged.
        """
        return


__all__ = ["NzbStatus"]