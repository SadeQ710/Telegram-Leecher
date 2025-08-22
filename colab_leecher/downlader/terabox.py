#================================================
#FILE: colab_leecher/downlader/terabox.py
#================================================
import aiohttp
import logging
from datetime import datetime
import random
from typing import Optional

from colab_leecher.utility.variables import Aria2c, TRANSFER, TaskError  # import global state
from colab_leecher.utility.handler import cancelTask
from colab_leecher.downlader.aria2 import aria2_Download
from colab_leecher.config import IS_VERIFY, VERIFY_EXPIRE, SHORTLINK_URL, SHORTLINK_API
from colab_leecher.utility.database import db_verify_status, db_update_verify_status
from shortzy import Shortzy


async def terabox_download(link: str, index: int, intended_filename: Optional[str] = None, user_id: Optional[int] = None) -> bool:
    """Download a Terabox link via an intermediate API with optional verification.

    When verification is enabled (``IS_VERIFY`` is True) and a
    ``user_id`` is provided the function checks whether the user has
    already verified their account.  If not verified or if their
    verification has expired the user is given a unique link to
    verify their account and the download is aborted.  Once verified
    the download proceeds using either the fast or slow link
    returned by the Terabox API.

    Parameters
    ----------
    link: str
        Terabox link to download.
    index: int
        Ordinal index used for status reporting.
    intended_filename: Optional[str]
        Optional filename hint; if not provided the API response
        title will be used.
    user_id: Optional[int]
        Telegram user ID for verification tracking.

    Returns
    -------
    bool
        ``True`` on success, ``False`` otherwise.
    """
    logger = logging.getLogger(__name__)
    payload = {"url": f"{link}"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    fast_download_url = ""
    slow_download_url = ""
    final_url_used = ""
    success = False
    # Use provided filename hint or fallback
    filename_hint = intended_filename or "Unknown Terabox File"

    # ------------------------------------------------------------------
    # Verification logic
    # ------------------------------------------------------------------
    if IS_VERIFY and user_id is not None:
        try:
            ver_doc = await db_verify_status(user_id)
            is_verified = bool(ver_doc.get("is_verified"))
            verified_time = float(ver_doc.get("verified_time", 0.0))
            now_ts = datetime.utcnow().timestamp()
            expired = is_verified and (now_ts - verified_time) > float(VERIFY_EXPIRE)
            if not is_verified or expired:
                # Either not verified or expired – generate a token and short link
                token = ver_doc.get("verify_token") or "".join(random.choices("0123456789abcdef", k=16))
                long_url = f"https://{SHORTLINK_URL}/verify/{user_id}/{token}"
                # Attempt to shorten the link via Shortzy
                try:
                    shortener = Shortzy(api_key=SHORTLINK_API)
                    result = shortener.short(long_url)
                    short_link = result.get("shortenedUrl") if isinstance(result, dict) else result
                    verify_link = short_link or long_url
                except Exception:
                    verify_link = long_url
                # Update verification record
                await db_update_verify_status(
                    user_id,
                    {
                        "verify_token": token,
                        "is_verified": False,
                        "verified_time": 0.0,
                        "link": verify_link,
                    },
                )
                await cancelTask(
                    "🔒 Verification required!\n"
                    "Click the link below to verify your account before downloading from Terabox:\n"
                    f"{verify_link}"
                )
                return False
        except Exception as exc:
            logger.warning(f"Verification check failed for user {user_id}: {exc}")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                "https://ytshorts.savetube.me/api/v1/terabox-downloader",
                data=payload,
                headers=headers,
                timeout=30,
            ) as response:
                response.raise_for_status()
                json_response = await response.json()
                # Extract file name and download URLs
                filename_hint = json_response.get("response", [{}])[0].get("title", filename_hint)
                res_map = json_response.get("response", [{}])[0].get("resolutions", {})
                fast_download_url = res_map.get("Fast Download", "")
                slow_download_url = res_map.get("HD Video", "")
        except Exception as e:
            error_reason = f"Failed to get Terabox link: {str(e)[:100]}"
            logger.error(f"Error getting Terabox download link for {link}: {e}")
            failed_info = {"link": link, "filename": filename_hint, "index": index, "reason": error_reason}
            if TaskError:
                TaskError.failed_links.append(failed_info)
            return False

        # Try Fast download first
        aria2_success = False
        try:
            logger.info(f"Attempting Terabox Fast Download for link index {index}")
            final_url_used = fast_download_url
            aria2_success = await aria2_Download(fast_download_url, index, filename_hint)
        except Exception as e:
            logger.warning(f"Fast download attempt failed for Terabox link {index}: {e}")
            aria2_success = False

        # If Fast download failed, try slow download
        if not aria2_success:
            logger.info(f"Fast download failed, trying Terabox Slow Download for link index {index}")
            try:
                final_url_used = slow_download_url
                aria2_success = await aria2_Download(slow_download_url, index, filename_hint)
            except Exception as e:
                error_reason = f"Slow Terabox DL failed: {str(e)[:100]}"
                logger.error(f"Slow download failed for Terabox link {index}: {e}")
                failed_info = {"link": link, "filename": filename_hint, "index": index, "reason": error_reason}
                if TaskError:
                    TaskError.failed_links.append(failed_info)
                aria2_success = False

    # Check final status from aria2 attempts
    if aria2_success:
        TRANSFER.successful_downloads.append({"url": link, "filename": filename_hint})
        success = True
    else:
        success = False
    return success
