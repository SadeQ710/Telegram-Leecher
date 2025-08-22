"""
Simplified SABnzbd client for managing NZB downloads.

This module exposes the `SabnzbdClient` class, which wraps the SABnzbd
API into an asynchronous client suitable for use within this project.
"""

from .requests import SabnzbdClient

__all__ = ["SabnzbdClient"]
