"""
Registers shorthand commands and utilities:
/mirror (/m), /leech (/l), /ytdl (/y), /count, /del (/delete), /stats
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
        "<b>♻️ Mirror Task » Send Me LINK(s) 🔗</b>

"
        "(Direct, Magnet, TG, Mega, GDrive, Debrid, NZB, bitso)

"
        "<code>https//link1.xyz
[name.ext]
{zip_pw}
(unzip_pw)</code>"
    )
    await task_starter(message, text)

@colab_bot.on_message(filters.command(["leech", "l"]) & filters.private)
async def leech_cmd(client, message):
    BOT.Mode.mode = "leech"; BOT.Mode.ytdl = False; BOT.Options.service_type = None
    text = (
        "<b>⚡ Leech Task » Send Me LINK(s) 🔗</b>

"
        "(Direct, Magnet, TG, Mega, GDrive, Debrid, NZB, bitso)

"
        "<code>https//link1.xyz
[name.ext]
{zip_pw}
(unzip_pw)</code>"
    )
    await task_starter(message, text)

@colab_bot.on_message(filters.command(["ytdl", "y"]) & filters.private)
async def ytdl_cmd(client, message):
    BOT.Mode.mode = "leech"; BOT.Mode.ytdl = True; BOT.Options.service_type = "ytdl"
    text = "<b>🏮 YTDL Leech » Send Me LINK(s) 🔗</b>

<code>https//link1.mp4</code>"
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
            "⚙️ <b>System Stats</b>

"
            f"CPU: <code>{cpu:.1f}%</code>
"
            f"RAM: <code>{sizeUnit(vm.used)}/{sizeUnit(vm.total)}</code>
"
            f"Disk: <code>{sizeUnit(du.used)}/{sizeUnit(du.total)}</code>"
        )
        await message.reply_text(text, quote=True)
    except Exception:
        log.exception("Stats command failed")
        await message.reply_text("Failed to fetch system stats.", quote=True)
