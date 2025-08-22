"""
Simplified dynamic bot settings module.

In the original mirror‑leech bot a comprehensive set of interactive
configuration options were available.  Those options required a
significant amount of code and integration with a database and have
been omitted here for brevity.  Instead this module exposes a small
collection of defaults which can be imported elsewhere in the project.
If you need to extend or change these values you may modify this
module directly or provide your own environment variables or
``.env`` file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

@dataclass
class BotSettings:
    """Container for runtime adjustable bot settings."""
    split_size: int = 2 * 1024 * 1024 * 1024  # default 2GiB
    rss_delay: int = 600  # seconds between RSS checks
    status_update_interval: int = 15  # seconds between status refreshes
    search_limit: int = 0  # search result limit
    default_upload: str = "rc"  # default upload type (rclone)
    # Additional simple settings can be added here as attributes

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


# Instantiate default settings
bot_settings = BotSettings()

__all__ = ["BotSettings", "bot_settings"]