"""
youtube‑dlp helper module.

This module wraps the functionality of ``yt_dlp`` into a class based
helper that reports progress via a shared status object.  The
original implementation in this repository exposed a pair of free
functions and used a global state container to communicate progress
back to the UI.  In order to more closely align with the design of
the upstream mirror‑leech project this refactoring encapsulates the
download logic in a ``YoutubeDLHelper`` class with methods for
metadata extraction and progress callbacks.  The asynchronous
``YTDL_Status`` coroutine remains as a thin wrapper around the
helper to integrate with the existing message update loop.

The helper populates the global ``YTDL`` object defined in
``colab_leecher.utility.variables`` so that other parts of the
application can continue to read progress information without
modification.
"""

from __future__ import annotations

import logging
from threading import Thread
from asyncio import sleep
from typing import Optional, Any

import yt_dlp

from colab_leecher.utility.handler import cancelTask
from colab_leecher.utility.variables import YTDL, MSG, Messages, Paths
from colab_leecher.utility.helper import (
    getTime,
    keyboard,
    sizeUnit,
    status_bar,
    sysINFO,
)

log = logging.getLogger(__name__)


class YoutubeDLHelper:
    """Class based wrapper for yt‑dlp downloads.

    A new instance should be created for each URL to download.  The
    instance holds a reference to the global YTDL status object and
    updates its attributes during the download via the progress hook.

    Parameters
    ----------
    url: str
        The URL of the media to download.
    """

    def __init__(self, url: str) -> None:
        self.url = url
        # Use the global YTDL state object for backwards compatibility
        self.status = YTDL
        self.info_dict: Optional[dict[str, Any]] = None
        # Prepare default options; will be patched during download
        self.ydl_opts = self._build_default_opts()

    # ------------------------------------------------------------------
    # Internal helper methods
    # ------------------------------------------------------------------
    def _build_default_opts(self) -> dict[str, Any]:
        """Return a default set of yt_dlp options.

        The options include progress hooks wired to this instance and
        reasonable defaults for format and thumbnail handling.  The
        downstream code may customise these options further if
        necessary.
        """
        return {
            "format": "best",
            "allow_multiple_video_streams": True,
            "allow_multiple_audio_streams": True,
            "writethumbnail": True,
            "writesubtitles": "srt",
            "extractor_args": {"subtitlesformat": "srt"},
            # Use our progress hook
            "progress_hooks": [self._on_download_progress],
            # Provide a logger instance
            "logger": self._MyLogger(self),
        }

    class _MyLogger:
        """Custom logger passed to yt_dlp.

        yt_dlp calls logger methods to provide debug, warning and
        error messages.  We only implement ``debug`` to surface
        playlist information and ignore the rest.
        """

        def __init__(self, helper: "YoutubeDLHelper") -> None:
            self.helper = helper

        def debug(self, msg: str) -> None:
            # When iterating through playlists yt_dlp emits messages of
            # the form ``[info] Writing video X of Y``.  We parse
            # these to set a temporary header on the global status so
            # that the UI can display a more useful message during
            # metadata extraction.
            if "item" in msg:
                parts = msg.split(" ")
                # Last two elements are typically "X" and "Y"
                try:
                    current, total = parts[-3], parts[-1]
                    self.helper.status.header = f"\n⏳ __Getting Video Information {current} of {total}__"
                except Exception:
                    pass

        def warning(self, msg: str) -> None:
            # Intentionally ignore warnings
            return

        def error(self, msg: str) -> None:
            # Suppress errors; they will be handled via exceptions
            return

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def extract_meta_data(self) -> str:
        """Extract metadata for the current URL.

        Uses yt_dlp in metadata‑only mode to fetch the video title.
        Returns the title if available, otherwise returns a fallback
        string.  Any exceptions will result in a cancelTask invocation
        and the fallback title being returned.
        """
        try:
            with yt_dlp.YoutubeDL({"logger": self._MyLogger(self)}) as ydl:
                info = ydl.extract_info(self.url, download=False)
                self.info_dict = info
                title = info.get("title") if info else None
                return title or "UNKNOWN DOWNLOAD NAME"
        except Exception as exc:
            # Report the error via cancelTask and return a placeholder
            await cancelTask(f"Can't download from this link. Because: {str(exc)}")
            return "UNKNOWN DOWNLOAD NAME"

    def download(self) -> None:
        """Perform the download synchronously.

        This method blocks until the download is complete.  It uses
        yt_dlp with the options prepared in ``_build_default_opts``.
        The output template is determined on the fly: for playlists a
        directory with the playlist title is created; for single
        downloads files are saved directly into the default download
        directory.  We intentionally avoid writing thumbnails into
        subdirectories so that subsequent upload code can find them
        predictably.
        """
        # Determine output templates based on metadata if available
        outtmpl = {}
        playlist_name: Optional[str] = None
        try:
            if not self.info_dict:
                with yt_dlp.YoutubeDL({"logger": self._MyLogger(self)}) as ydl:
                    self.info_dict = ydl.extract_info(self.url, download=False)
            if self.info_dict and self.info_dict.get("_type") == "playlist":
                playlist_name = self.info_dict.get("title", "playlist")
                # Ensure playlist directory exists
                import os
                from os import path as ospath
                if not ospath.exists(os.path.join(Paths.down_path, playlist_name)):
                    os.makedirs(os.path.join(Paths.down_path, playlist_name), exist_ok=True)
                outtmpl = {
                    "default": f"{Paths.down_path}/{playlist_name}/%(title)s.%(ext)s",
                    "thumbnail": f"{Paths.thumbnail_ytdl}/%(id)s.%(ext)s",
                }
            else:
                outtmpl = {
                    "default": f"{Paths.down_path}/%(id)s.%(ext)s",
                    "thumbnail": f"{Paths.thumbnail_ytdl}/%(id)s.%(ext)s",
                }
        except Exception:
            # Fall back to simple output template
            outtmpl = {
                "default": f"{Paths.down_path}/%(id)s.%(ext)s",
                "thumbnail": f"{Paths.thumbnail_ytdl}/%(id)s.%(ext)s",
            }
        # Inject the output template into options
        opts = self.ydl_opts.copy()
        opts["outtmpl"] = outtmpl
        # Ensure the thumbnail directory exists
        import os
        if not os.path.exists(Paths.thumbnail_ytdl):
            os.makedirs(Paths.thumbnail_ytdl, exist_ok=True)
        # Perform the download
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                ydl.download([self.url])
            except Exception as exc:
                log.error(f"YTDL ERROR: {exc}")

    # ------------------------------------------------------------------
    # Callback
    # ------------------------------------------------------------------
    def _on_download_progress(self, d: dict[str, Any]) -> None:
        """Progress hook for yt_dlp.

        This method is invoked by yt_dlp for each download progress
        event.  It updates the global ``YTDL`` status object so that
        asynchronous UI code can report progress.  We handle both
        downloading and extracting events.  In the event of an
        exception the status fields are left unchanged.
        """
        try:
            status = d.get("status")
            if status == "downloading":
                total_bytes = d.get("total_bytes") or 0
                downloaded = d.get("downloaded_bytes") or 0
                speed = d.get("speed") or 0
                eta = d.get("eta") or 0
                # If total is known compute percentage; else rely on
                # provided downloaded_percent if available
                if total_bytes:
                    percent = round((downloaded * 100.0) / float(total_bytes), 2)
                else:
                    percent = d.get("downloaded_percent", 0)
                # Update global YTDL status object
                self.status.header = ""
                self.status.speed = sizeUnit(speed) if speed else "N/A"
                self.status.percentage = percent
                self.status.eta = getTime(eta) if eta else "N/A"
                self.status.done = sizeUnit(downloaded) if downloaded else "N/A"
                self.status.left = sizeUnit(total_bytes) if total_bytes else "N/A"
            elif status == "finished":
                # Finished downloading; leave status fields as final values
                pass
        except Exception:
            # Suppress any errors in the progress hook to avoid
            # breaking the download process
            pass


async def YTDL_Status(link: str, num: int) -> None:
    """Asynchronous status monitor for a yt_dlp download.

    Creates a ``YoutubeDLHelper`` instance for the provided link and
    launches the download on a background thread.  While the thread
    is active this coroutine periodically updates the status message
    displayed to the user.  Once the download completes the loop
    exits.  Errors during metadata extraction or download will
    propagate via the global TaskError state set by ``cancelTask``.

    Parameters
    ----------
    link: str
        URL to download.
    num: int
        Ordinal number used when formatting the status header.
    """
    helper = YoutubeDLHelper(link)
    # Extract the media title for display
    name = await helper.extract_meta_data()
    Messages.status_head = (
        f"<b>📥 DOWNLOADING FROM » </b><i>🔗Link {str(num).zfill(2)}</i>\n\n<code>{name}</code>\n"
    )
    # Launch the synchronous download on a worker thread
    thread = Thread(target=helper.download, name="YouTubeDL", daemon=True)
    thread.start()
    # Monitor the download progress until it finishes
    while thread.is_alive():
        # If status.header is populated then we display the header along
        # with system info; otherwise we show a progress bar
        if YTDL.header:
            sys_text = sysINFO()
            message_text = Messages.task_msg + Messages.status_head + YTDL.header + sys_text
            try:
                await MSG.status_msg.edit_text(
                    text=message_text,
                    reply_markup=keyboard(),
                )
            except Exception:
                pass
        else:
            try:
                await status_bar(
                    down_msg=Messages.status_head,
                    speed=YTDL.speed,
                    percentage=float(YTDL.percentage),
                    eta=YTDL.eta,
                    done=YTDL.done,
                    left=YTDL.left,
                    engine="Xr-YtDL 🏮",
                )
            except Exception:
                pass
        await sleep(2.5)


async def get_YT_Name(link: str) -> str:
    """Return the name of a YouTube resource.

    This is a convenience wrapper around ``YoutubeDLHelper.extract_meta_data``.
    It returns the title of the video or a fallback if the title cannot
    be extracted.
    """
    helper = YoutubeDLHelper(link)
    return await helper.extract_meta_data()


__all__ = [
    "YoutubeDLHelper",
    "YTDL_Status",
    "get_YT_Name",
]