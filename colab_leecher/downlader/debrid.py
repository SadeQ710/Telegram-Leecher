"""
Debrid downloader module.

This module provides a simple asynchronous function to handle downloads
via debrid services.  For each URL provided, it attempts to download
the file using the generic ``http_download_logic`` defined in
``manager.py``.  At present this implementation does not attempt to
convert share links into direct links via external APIs (e.g. using
Real‑Debrid or other services); instead it simply downloads the URL
directly.  To integrate with a debrid provider that requires link
resolution, extend this function accordingly.
"""

from __future__ import annotations

import os
import logging
from typing import Iterable, List, Optional

from .manager import http_download_logic  # type: ignore
from ..utility.variables import Paths, Messages, TaskError, TRANSFER  # type: ignore

LOGGER = logging.getLogger(__name__)


async def debrid_download(urls: Iterable[str], filenames: Optional[List[str]] = None) -> bool:
    """
    Download a batch of direct links via Debrid.

    :param urls: An iterable of URLs to download.
    :param filenames: Optional list of target file names.  If provided, its
        length should match ``urls``; otherwise a generic name will be
        generated for each link.
    :returns: ``True`` if all downloads succeed, ``False`` otherwise.
    """
    urls_list = list(urls)
    total = len(urls_list)
    filenames = filenames or [f"debrid_file_{i+1}" for i in range(total)]
    if len(filenames) != total:
        LOGGER.error("Debrid download: number of filenames does not match number of URLs")
        return False
    all_success = True
    headers = {"User-Agent": "Mozilla/5.0"}
    cookies = {}  # Add cookie support if needed for specific debrid services
    for idx, (url, fname) in enumerate(zip(urls_list, filenames), start=1):
        dest = os.path.join(Paths.down_path, fname)
        try:
            # ensure the destination directory exists
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            success = await http_download_logic(
                url=url,
                file_path=dest,
                display_name=fname,
                headers=headers,
                cookies=cookies,
                link_num=idx,
                total_links=total,
            )
            if not success:
                all_success = False
        except Exception as exc:
            LOGGER.error(f"Debrid download error for {url}: {exc}")
            all_success = False
    return all_success
