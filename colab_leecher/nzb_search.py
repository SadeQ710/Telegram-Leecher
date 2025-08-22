"""
NZB search utility using NZBHydra2.

This module defines a helper function to query an NZBHydra instance.  It
expects the Hydra API base URL and API key to be provided via the
project's ``credentials.json`` file or environment variables (``HYDRA_URL``
and ``HYDRA_API_KEY``).  The search results are returned as a list of
dicts containing the title, link and size (in bytes).
"""

from __future__ import annotations

import json
import os
import logging
from typing import List, Dict, Optional
from xml.etree import ElementTree as ET

import aiohttp

LOGGER = logging.getLogger(__name__)

def _load_hydra_credentials() -> tuple[str | None, str | None]:
    """
    Load Hydra API credentials from ``credentials.json`` or environment.
    Returns (base_url, api_key).
    """
    cred_path = os.path.join(os.getcwd(), "credentials.json")
    base_url = None
    api_key = None
    if os.path.exists(cred_path):
        try:
            with open(cred_path, "r", encoding="utf-8") as f:
                creds = json.load(f)
            base_url = creds.get("HYDRA_URL")
            api_key = creds.get("HYDRA_API_KEY")
        except Exception as exc:
            LOGGER.warning(f"Failed to read credentials.json: {exc}")
    base_url = base_url or os.environ.get("HYDRA_URL")
    api_key = api_key or os.environ.get("HYDRA_API_KEY")
    return base_url, api_key


async def search_nzb(query: str, limit: int = 50) -> Optional[List[Dict[str, str]]]:
    """
    Search an NZBHydra2 indexer and return a list of result items.

    Each result dict contains ``title``, ``link`` and ``size`` keys.  If
    no results are found or the search fails, ``None`` is returned.
    """
    base_url, api_key = _load_hydra_credentials()
    if not base_url or not api_key:
        LOGGER.error("Hydra credentials are missing. Set HYDRA_URL and HYDRA_API_KEY in credentials.json or environment variables.")
        return None
    search_url = f"{base_url.rstrip('/')}/api"
    params = {
        "apikey": api_key,
        "t": "search",
        "q": query,
        "limit": limit,
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(search_url, params=params, headers=headers) as response:
                if response.status != 200:
                    LOGGER.error(f"Hydra search failed: HTTP {response.status}")
                    return None
                text = await response.text()
                try:
                    root = ET.fromstring(text)
                except ET.ParseError:
                    LOGGER.error("Failed to parse Hydra XML response")
                    return None
                items: List[Dict[str, str]] = []
                for item in root.findall(".//item"):
                    title = item.findtext("title") or ""
                    link = item.findtext("link") or ""
                    size = item.findtext("size") or "0"
                    items.append({"title": title, "link": link, "size": size})
                return items
    except Exception as exc:
        LOGGER.error(f"Hydra search error: {exc}")
        return None
