"""
NZB downloader implementation.

This module provides a simple interface for adding NZB links to a
SABnzbd server.  It relies on the minimal `SabnzbdClient` defined in
``colab_leecher.sabnzbdapi.requests``.  Credentials are loaded from
the project's ``credentials.json`` file if present, or from
environment variables.  The function returns a boolean indicating
whether all links were successfully enqueued.
"""

from __future__ import annotations

import json
import os
import logging
from typing import Iterable, List

from ..sabnzbdapi import SabnzbdClient

LOGGER = logging.getLogger(__name__)

def _load_sab_credentials() -> tuple[str | None, str | None]:
    """
    Load SABnzbd API credentials from ``credentials.json`` or
    environment variables.  Returns a tuple of (base_url, api_key).
    If either value is missing, ``None`` is returned in its place.
    """
    cred_path = os.path.join(os.getcwd(), "credentials.json")
    base_url = None
    api_key = None
    if os.path.exists(cred_path):
        try:
            with open(cred_path, "r", encoding="utf-8") as f:
                creds = json.load(f)
            base_url = creds.get("SABNZBD_URL") or creds.get("SABNZBD_HOST")
            api_key = creds.get("SABNZBD_API_KEY")
        except Exception as exc:
            LOGGER.warning(f"Failed to read credentials.json: {exc}")
    # Fallback to environment variables
    base_url = base_url or os.environ.get("SABNZBD_URL")
    api_key = api_key or os.environ.get("SABNZBD_API_KEY")
    return base_url, api_key


async def nzb_download(links: Iterable[str]) -> bool:
    """
    Enqueue one or more NZB links for downloading via SABnzbd.

    :param links: An iterable of NZB URLs to enqueue.  Each URL is
        submitted to SABnzbd using the ``add_uri`` API.  The function
        waits for all submissions to complete but does **not** monitor
        their progress or completion.
    :returns: ``True`` if all submissions succeeded, otherwise ``False``.
    """
    base_url, api_key = _load_sab_credentials()
    if not base_url or not api_key:
        LOGGER.error("SABnzbd credentials are missing. Set SABNZBD_URL and SABNZBD_API_KEY in credentials.json or environment variables.")
        return False
    client = SabnzbdClient(host=base_url, api_key=api_key)
    all_success = True
    for link in links:
        url = str(link).strip()
        if not url:
            continue
        try:
            res = await client.add_uri(url=url)
            if not res.get("status"):
                LOGGER.error(f"Failed to add NZB link: {url}")
                all_success = False
        except Exception as exc:
            LOGGER.error(f"Error adding NZB link {url}: {exc}")
            all_success = False
    # Do not close the client here; allow reuse for multiple calls
    return all_success
