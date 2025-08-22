"""
This script has been deprecated in the refactored version of the Colab Leecher project.

Previously, this file contained a Google Colab‑specific setup routine with hard‑coded API
credentials and automatic repository cloning.  This implementation posed serious security
risks because sensitive information (like bot tokens and chat IDs) was embedded directly
in the source code.  In addition, running arbitrary shell commands via ``subprocess`` with
``shell=True`` opened the door to command injection vulnerabilities.

In the corrected project, all credential management is handled via external configuration
files or environment variables.  The bot can be started directly by running the package
``python -m colab_leecher`` once your credentials are configured.  See the accompanying
``README.md`` for instructions on creating a ``credentials.json`` file or setting the
necessary environment variables.

If you relied on the previous Colab workflow, migrate to the new workflow by
following these steps:

1.  Copy ``credentials.example.json`` to ``credentials.json`` and fill in your values.
2.  Install the dependencies listed in ``requirements.txt`` using ``pip install -r requirements.txt``.
3.  Run the bot with ``python -m colab_leecher``.

This file remains as a placeholder to avoid breaking imports in legacy notebooks.  It
prints a helpful message when executed and exits.
"""

def main():  # pragma: no cover
    import sys
    print(
        "The Colab setup script has been removed.\n"
        "Please configure your credentials in credentials.json or environment variables and run:\n"
        "\n"
        "    python -m colab_leecher\n"
        "\n"
        "Refer to the README for more information."
    )
    sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

# 1) gdrive_utils.py (Drive size + delete helpers)
gdrive_utils_src = textwrap.dedent(r'''
"""
Utility functions for simple Google Drive operations (count/delete).
They reuse your project's existing Drive client and helpers.

Requires:
- from .downlader.gdrive import build_service, getIDFromURL, get_Gfolder_size
- from .utility.variables import Gdrive
"""
import logging
from .downlader.gdrive import build_service, getIDFromURL, get_Gfolder_size
from .utility.variables import Gdrive

log = logging.getLogger(__name__)

async def count_link(link: str) -> int:
    """Return total size in bytes of the target Drive file/folder, or -1 on failure."""
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
    """Delete a Drive file/folder by link. Returns True on success."""
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
''').strip("\n")

# 2) aliases.py (registers aliases + /count,/del,/stats)
aliases_src = textwrap.dedent(r'''
"""
Lightweight commands to reach feature parity without Docker:

- /mirror (/m)  -> same prompt/flow as your GDrive upload
- /leech (/l)   -> same prompt/flow as your Telegram upload
- /ytdl  (/y)   -> same prompt/flow as your yt-dlp leech
- /count        -> size of Drive link
- /del | /delete-> delete Drive link
- /stats        -> CPU/RAM/Disk via psutil
"""
import logging
from pyrogram import filters
from . import colab_bot
from .utility.variables import BOT
from .utility.task_manager import task_starter
from .utility.helper import sizeUnit
from .gdrive_utils import count_link, delete_link

log = logging.getLogger(__name__)

@colab_bot.on_message(filters.command(["mirror", "m"]) & filters.private)
async def mirror_cmd(client, message):
    BOT.Mode.mode = "mirror"; BOT.Mode.ytdl = False; BOT.Options.service_type = None
    text = (
        "<b>♻️ Mirror Task » Send Me THEM LINK(s) 🔗</b>\n\n"
        "(Direct, Magnet, TG, Mega, GDrive, Debrid, NZB, bitso)\n\n"
        "<code>https//link1.xyz\n[name.ext]\n{zip_pw}\n(unzip_pw)</code>"
    )
    await task_starter(message, text)

@colab_bot.on_message(filters.command(["leech", "l"]) & filters.private)
async def leech_cmd(client, message):
    BOT.Mode.mode = "leech"; BOT.Mode.ytdl = False; BOT.Options.service_type = None
    text = (
        "<b>⚡ Leech Task » Send Me THEM LINK(s) 🔗</b>\n\n"
        "(Direct, Magnet, TG, Mega, GDrive, Debrid, NZB, bitso)\n\n"
        "<code>https//link1.xyz\n[name.ext]\n{zip_pw}\n(unzip_pw)</code>"
    )
    await task_starter(message, text)

@colab_bot.on_message(filters.command(["ytdl", "y"]) & filters.private)
async def ytdl_cmd(client, message):
    BOT.Mode.mode = "leech"; BOT.Mode.ytdl = True; BOT.Options.service_type = "ytdl"
    text = (
        "<b>🏮 YTDL Leech » Send Me LINK(s) 🔗</b>\n\n"
        "<code>https//link1.mp4</code>"
    )
    await task_starter(message, text)

@colab_bot.on_message(filters.command("count") & filters.private)
async def count_cmd(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text("Usage: /count <GDrive link>", quote=True); return
    link = args[1].strip()
    size = await count_link(link)
    if size < 0:
        await message.reply_text("Failed to fetch size. Check the link and try again.", quote=True)
    else:
        await message.reply_text(f"📦 Size: {sizeUnit(size)}", quote=True)

@colab_bot.on_message(filters.command(["del", "delete"]) & filters.private)
async def del_cmd(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text("Usage: /del <GDrive link>", quote=True); return
    link = args[1].strip()
    ok = await delete_link(link)
    await message.reply_text("✅ Deleted from Drive." if ok else "❌ Failed to delete from Drive.", quote=True)

@colab_bot.on_message(filters.command("stats") & filters.private)
async def stats_cmd(client, message):
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=1)
        vm = psutil.virtual_memory()
        du = psutil.disk_usage("/")
        text = (
            "⚙️ <b>System Stats</b>\n\n"
            f"CPU: <code>{cpu:.1f}%</code>\n"
            f"RAM: <code>{sizeUnit(vm.used)}/{sizeUnit(vm.total)}</code>\n"
            f"Disk: <code>{sizeUnit(du.used)}/{sizeUnit(du.total)}</code>"
        )
        await message.reply_text(text, quote=True)
    except Exception:
        log.exception("Stats command failed")
        await message.reply_text("Failed to fetch system stats.", quote=True)
''').strip("\n")

# Write files
write_file(os.path.join(colab_dir_path, "gdrive_utils.py"), gdrive_utils_src)
write_file(os.path.join(colab_dir_path, "aliases.py"), aliases_src)
log.info("Wrote colab_leecher/gdrive_utils.py and colab_leecher/aliases.py")

# Patch __main__.py to import aliases (idempotent)
with open(main_script_path, "r", encoding="utf-8", errors="ignore") as f:
    main_txt = f.read()
if "from . import aliases" not in main_txt:
    lines = main_txt.splitlines()
    inserted = False
    for i, line in enumerate(lines):
        if re.search(r"from\\s+colab_leecher\\s+import\\s+.*colab_bot", line):
            lines.insert(i+1, "from . import aliases  # registers /mirror,/leech,/ytdl,/count,/del,/stats")
            inserted = True; break
    if not inserted:
        lines.insert(0, "from . import aliases  # registers /mirror,/leech,/ytdl,/count,/del,/stats")
    with open(main_script_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    log.info("Patched __main__.py to import aliases.")
else:
    log.info("Import already present in __main__.py")

# ===== Sanity checks =====
log.info(f"Using repository path: {repo_path}")
ipython.system(f'ls -l "{colab_dir_path}" | sed -n "1,80p"')
ipython.system(f'grep -n "from \\. import aliases" "{main_script_path}" || true')

# ===== Final: start bot =====
Working = False; _Thread.join()
setup_ok = valid_creds

if setup_ok:
    if os.path.exists(session_file):
        try:
            os.remove(session_file); log.info(f"Removed previous session: {session_file}")
        except OSError as e:
            log.warning(f"Could not remove session file: {e}")

    if os.getcwd() != repo_path:
        ipython.run_line_magic('cd', repo_path); log.info(f"Changed directory to {repo_path}")

    log.info("--- Verification ---")
    ipython.system(f'head -n 20 "{main_script_path}"')

    log.info(f"Attempting to start bot module '{bot_main_module}' from {repo_path}...")
    try:
        exit_code = ipython.system(f'python3 -m {bot_main_module}')
        log.info(f"Bot process finished (exit code: {exit_code}).")
    except Exception as e:
        log.critical(f"CRITICAL ERROR during bot startup: {e}", exc_info=True)
else:
    print("\n-----------------------------------------------\n Bot setup failed or invalid creds. Check logs above.\n-----------------------------------------------")
