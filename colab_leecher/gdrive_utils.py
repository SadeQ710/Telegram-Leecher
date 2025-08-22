"""
Utility functions for simple Google Drive operations (count/delete).
Reuses project's existing Drive client and helpers.
"""
import logging
from .downlader.gdrive import build_service, getIDFromURL, get_Gfolder_size
from .utility.variables import Gdrive

log = logging.getLogger(__name__)

async def count_link(link: str) -> int:
    try:
        await build_service()
        file_id = await getIDFromURL(link)
        if not file_id:
            log.error("Unable to extract file ID from link: %s", link)
            return -1
        return await get_Gfolder_size(file_id)
    except Exception:
        log.exception("Drive count failed for %s", link)
        return -1

async def delete_link(link: str) -> bool:
    try:
        await build_service()
        file_id = await getIDFromURL(link)
        if not file_id:
            log.error("Unable to extract file ID for deletion: %s", link)
            return False
        import asyncio
        loop = asyncio.get_running_loop()
        def _do_delete():
            return Gdrive.service.files().delete(
                fileId=file_id, supportsAllDrives=True
            ).execute()
        if loop:
            await loop.run_in_executor(None, _do_delete)
        else:
            _do_delete()
        log.info("Deleted Drive item: %s", file_id)
        return True
    except Exception:
        log.exception("Drive delete failed for %s", link)
        return False
