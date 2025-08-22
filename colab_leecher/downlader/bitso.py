"""
Bitso downloader module.

This module implements a simple downloader for the Bitso file hosting
service.  It uses the generic ``http_download_logic`` function from
``manager.py`` to handle HTTP downloads.  To authenticate with Bitso,
the caller must supply the appropriate cookies (``_identity`` and
``PHPSESSID``); these should be stored in the bot settings (see
``BITSO_IDENTITY_COOKIE`` and ``BITSO_PHPSESSID_COOKIE`` in
``main.py``).
"""

from __future__ import annotations

import os
import logging
from typing import Iterable, List, Optional

from .manager import http_download_logic  # type: ignore
from ..utility.variables import Paths, Messages, TaskError, TRANSFER, BOT  # type: ignore

LOGGER = logging.getLogger(__name__)


async def bitso_download(urls: Iterable[str], filenames: Optional[List[str]] = None) -> bool:
    """
    Download a batch of files from Bitso.

    :param urls: An iterable of Bitso download URLs.
    :param filenames: Optional list of filenames.  If provided its length
        should equal the number of ``urls``; otherwise a generic name
        will be generated.
    :returns: ``True`` on complete success, else ``False``.
    """
    urls_list = list(urls)
    total = len(urls_list)
    filenames = filenames or [f"bitso_file_{i+1}" for i in range(total)]
    if len(filenames) != total:
        LOGGER.error("Bitso download: number of filenames does not match number of URLs")
        return False
    all_success = True
    # Retrieve cookies from BOT settings if available
    id_cookie = getattr(BOT.Setting, 'bitso_identity_cookie', '')
    sess_cookie = getattr(BOT.Setting, 'bitso_phpsessid_cookie', '')
    cookies = {}
    if id_cookie:
        cookies["_identity"] = id_cookie
    if sess_cookie:
        cookies["PHPSESSID"] = sess_cookie
    headers = {
        "Referer": "https://panel.bitso.ir/",
        "User-Agent": "Mozilla/5.0",
    }
    for idx, (url, fname) in enumerate(zip(urls_list, filenames), start=1):
        dest = os.path.join(Paths.down_path, fname)
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            success = await http_download_logic(
                url=url.strip(),
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
            LOGGER.error(f"Bitso download error for {url}: {exc}")
            all_success = False
    return all_success
