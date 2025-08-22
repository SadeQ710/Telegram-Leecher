"""
JDownloader integration stubs.

This package exposes a minimal helper class used to enqueue
downloads via a running JDownloader instance.  The upstream
mirror‑leech project provided a sophisticated wrapper around the
MyJDownloader API which handled authentication, link checking,
package creation and status polling.  For the purposes of this
exercise we provide a simple class with no‑op methods that can be
extended in the future.
"""

from __future__ import annotations

from typing import Iterable


class JDownloaderHelper:
    """A bare bones helper to interact with JDownloader.

    Parameters
    ----------
    host: str
        Base URL of the JDownloader API.  Ignored in this stub.
    username: str
        Username for authentication.  Ignored in this stub.
    password: str
        Password for authentication.  Ignored in this stub.
    """

    def __init__(self, host: str = "", username: str = "", password: str = "") -> None:
        # Store credentials for potential future use
        self.host = host
        self.username = username
        self.password = password

    async def add_links(self, links: Iterable[str]) -> bool:
        """Add a collection of links to JDownloader.

        In this stub implementation the method simply logs the
        invocation and returns ``True`` to indicate that the links
        would have been accepted.  A real implementation would
        perform API calls here.
        """
        import logging

        logger = logging.getLogger(__name__)
        logger.info(f"JDownloaderHelper.add_links called with {len(list(links))} link(s)")
        return True


__all__ = ["JDownloaderHelper"]