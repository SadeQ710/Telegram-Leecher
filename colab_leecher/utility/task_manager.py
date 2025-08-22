# /content/Telegram-Leecher/colab_leecher/utility/task_manager.py
import pytz
import shutil
import logging
import os
import random
import aiohttp
import aiofiles
import asyncio
from time import time
from datetime import datetime
from asyncio import sleep
from os import makedirs, path as ospath, system
from .. import OWNER, colab_bot, DUMP_ID
from ..downlader.manager import calDownSize, get_d_name, downloadManager
from .helper import (
    getSize,
    applyCustomName,
    keyboard,
    sysINFO,
    is_google_drive,
    is_telegram,
    is_ytdl_link,
    is_mega,
    is_terabox,
    is_torrent,
    clean_filename,
    sizeUnit,
    getTime,
    speedETA,
    status_bar,
)
from .handler import (
    Leech,
    Unzip_Handler,
    Zip_Handler,
    SendLogs,
    cancelTask,
)

from .variables import (
    BOT,
    MSG,
    BotTimes,
    Messages,
    Paths,
    Aria2c,
    TaskError,
    TRANSFER,
)

# Maintain a global set of currently running tasks identified by their source links.
# This allows duplicate tasks to be detected and rejected.  Each task key is a
# tuple of its source links in sorted order.  When a new task starts the
# corresponding key is added to this set; when the task completes it is
# removed.  See ``taskScheduler`` for usage.
running_tasks: set[tuple[str, ...]] = set()


log = logging.getLogger(__name__)


async def task_starter(message, text):
    """Handles the initial command, replies, and sets started state."""
    global BOT
    log.info(f"task_starter called by user {message.from_user.id} for mode '{BOT.Mode.mode}'")
    try:
        await message.delete()
        log.debug("User command message deleted.")
    except Exception as e:
        log.error(f"Failed to delete user command message: {e}")

    if not BOT.State.task_going:
        BOT.State.started = True 
        log.debug(f"BOT.State.started=True. BOT.State.task_going={BOT.State.task_going}")
        log.info("Task not going. Replying to user to send links/path.")
        try:
            src_request_msg = await message.reply_text(text)
            log.info("Reply prompt sent.")
            return src_request_msg 
        except Exception as e:
            log.error(f"Failed reply in task_starter: {e}", exc_info=True)
            BOT.State.started = False 
            try: await message.reply_text(f"Oops! Error sending prompt: {e}") 
            except Exception: pass
            return None
    else:
        
        log.warning("Task already going. Informing user.")
        try:
            msg = await message.reply_text("**I’m already on it! Wait up! 💯🔥**")
            await sleep(15) 
            await msg.delete() 
        except Exception as e:
            log.error(f"Failed 'task ongoing' message: {e}")
        return None


async def taskScheduler():
    """Main function to orchestrate the download/upload task."""
    global BOT, MSG, BotTimes, Messages, Paths, TRANSFER, TaskError, running_tasks
    selected_service = BOT.Options.service_type
    log.info(f"taskScheduler entered. Mode: {BOT.Mode.mode}, Type: {BOT.Mode.type}, Service: {selected_service}")
    # Duplicate task detection: compose a key from the sorted list of source links.
    task_key = tuple(sorted(str(s) for s in BOT.SOURCE))
    if task_key in running_tasks:
        log.warning("Duplicate task detected, aborting scheduler call.")
        await cancelTask("An identical task is already running. Please wait until it finishes.")
        return
    # Register this task as running
    running_tasks.add(task_key)
    src_text = []
    is_dualzip = (BOT.Mode.type == "undzip")
    is_unzip = (BOT.Mode.type == "unzip")
    is_zip = (BOT.Mode.type == "zip")
    current_mode = BOT.Mode.mode
    is_dir = (current_mode == "dir-leech")

    # Store original download path in case it's modified (e.g., for zip mode)
    original_Paths_down_path = Paths.down_path

    try: # Main try block for the entire task
        TRANSFER.reset() # Reset transfer statistics
        log.debug("Transfer state reset.")
        Messages.download_name = "" # Reset download name context
        Messages.task_msg = f"<b> TASK MODE » </b>"
        # Prepare display names for logs/status
        mode_display_name = current_mode.replace("-leech", "").replace("-mirror", "").capitalize()
        type_display_name = BOT.Mode.type.capitalize()
        upload_display_name = BOT.Setting.stream_upload
        service_str = f" ({selected_service.capitalize()})" if selected_service else ""
        # Construct task description string for dump chat
        dump_task_mode_str = f"<i>{type_display_name} {mode_display_name}{service_str} as {upload_display_name}</i>" if current_mode != "mirror" else f"<i>{type_display_name} {mode_display_name}{service_str}</i>"
        Messages.dump_task = Messages.task_msg + dump_task_mode_str + "\n\n<b>🖇️ SOURCES » </b>"
        Messages.status_head = f"<b>📥 DOWNLOADING » </b>\n" # Initial status header
        TaskError.state = False # Reset error state
        TaskError.text = "" # Reset error text

        # --- Source Link Processing & Formatting for Dump Message ---
        if is_dir:
            source_path = BOT.SOURCE[0]
            log.info(f"Dir mode. Path: {source_path}")
            if not ospath.exists(source_path):
                TaskError.state = True
                TaskError.text = "Directory Path Not Found"
                log.error(TaskError.text)
                # No need to explicitly return here, finally block will handle cleanup/cancel if needed
            else:
                 # Create temp dir if needed (although not used directly here)
                 if not ospath.exists(Paths.temp_dirleech_path): makedirs(Paths.temp_dirleech_path)
                 Messages.dump_task += f"\n\n📂 <code>{source_path}</code>"
                 TRANSFER.total_down_size = getSize(source_path) # Pre-calculate size
                 Messages.download_name = ospath.basename(source_path) # Set initial name
                 log.debug(f"Dir size: {sizeUnit(TRANSFER.total_down_size)}, Name: {Messages.download_name}")
        else: # Link processing modes
            log.info(f"Link mode. Processing {len(BOT.SOURCE)} sources.")
            for link in BOT.SOURCE:
                # Icon logic based on service type or link type
                ida = "🔗" # Default icon
                if selected_service == 'delta': ida = "💧"
                elif selected_service == 'nzbcloud': ida = "☁️"
                elif selected_service == 'bitso': ida = "🪙"
                elif selected_service == 'ytdl' or BOT.Mode.ytdl: ida = "🏮"
                elif is_telegram(link): ida = "💬"
                elif is_google_drive(link): ida = "♻️"
                elif is_torrent(link): ida = "🧲"; Messages.caution_msg = "" # No caution for torrents
                elif is_terabox(link): ida = "🍑"
                elif is_mega(link): ida = "💾"
                # Add other auto-detections if needed

                code_link = f"\n\n{ida} <code>{link}</code>"
                # Split dump message if it gets too long
                if len(Messages.dump_task + code_link) >= 4096:
                     src_text.append(Messages.dump_task)
                     Messages.dump_task = code_link # Start new message part
                else:
                     Messages.dump_task += code_link

        # Append date and final part of dump message
        cdt = datetime.now(pytz.timezone("Asia/Kolkata"))
        dt = cdt.strftime(" %d-%m-%Y")
        Messages.dump_task += f"\n\n<b>📆 Task Date » </b><i>{dt}</i>"
        src_text.append(Messages.dump_task)

        # --- Environment Setup & Thumbnail Handling ---
        log.info("Setting up work environment...")
        # Clean work path if it exists, then recreate needed dirs
        if ospath.exists(Paths.WORK_PATH): shutil.rmtree(Paths.WORK_PATH)
        makedirs(Paths.WORK_PATH, exist_ok=True)
        makedirs(Paths.down_path, exist_ok=True)

        # --- Conditional Random Thumbnail Download ---
        thumbnail_urls = [
             #LaurenBrzozowski
	    "https://simp6.jpg5.su/images3/Lauren.Brzozowski.01ad13a46aafeaf4e1.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.02ae24dcac85c86b14.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.0347b21b248459cae1.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.041a2d05252490d1b9.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.05c1f4f985f4b4a71c.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.0665ce68f1898ada37.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.07cae587c0ca6450c2.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.08aefcba910a3722f6.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.09faf7442c49e21958.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.10cadaf55e348828fd.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.11a67a5e087e244e8e.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.12307f8492bf5ee96b.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.13deee7c265bc32a24.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.14340cf8590876cd88.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.15ec4ca2fc62b19cff.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.165fe672bc6c6412e9.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.17480674bad71a7e46.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.18ad9b5d63ea67ce97.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.192074013c10b7b42d.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.203224849f696e38e1.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.211511177e50fc3521.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.22689f64a0b1f966ff.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.237d8833cf6d261be8.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.246b40931af32df8aa.jpg",
            "https://simp6.jpg5.su/images3/Lauren.Brzozowski.2539f231030f133bc9.jpg",
            #kittylever
            "https://simp6.jpg5.su/images3/Kitty.Lever.01e1040a634e533677.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.025e5426854cd8a5ec.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.036282730fc203e055.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.0405037d63558199b9.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.05bb4bd14d22eb5656.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.061e5fbf5c552c55d0.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.07fc80f432d7879d4c.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.08b7020985e47194a5.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.09e839a0be69fb3a02.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.10642d93a0ceb83a2b.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.11e3c3995f14d3b19c.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.12c1eea97997bb5244.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.130ff319d96dc1c0cc.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.145166502f5dac647f.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.15e81e9e353ce81a1f.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.16bd6fe6233250cec8.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.17c4e9a9b401edaf24.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.184ac1c86d43cb422b.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.19da47a39bb49bf7e3.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.209939d5b5db2b64e2.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.21dedfa338cca6f7a4.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.2259dc32fcea0545e0.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.232833415fc2e7ee29.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.2464d96a391f21b7cc.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.25bd0c6c44faf84cec.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.26da3970bdbbea4a90.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.2763623fa8f1bc4326.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.28eddcd58960d74719.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.293108b8cdbe1ae4ab.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.300c71f573ffaee25f.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.3124813d2d30cf9235.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.322060f0bafc234124.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.3358b7c93c26d11bb2.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.34b73529d302ed29da.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.356df70c3a63a74fc6.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.3628a6172c7b7d3d4c.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.378ccbb809ee5c1890.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.3868eb04fd1fac78cf.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.39bd5d1380e95fcc2a.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.405429bab5d45f7a30.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.410c4ad39cdcc13158.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.4241c8d2a6d2c327e9.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.43380e08b34ed8a38f.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.448ade2b5d138db6fe.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.45ddf2e2d4b18e5a01.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.46dae8c66b05eafe54.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.47a363e34cc2ccce1e.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.487f2558747b8cef52.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.4977fe6993841b7fbf.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.50ae73c94bb769f16c.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.51b2600ab0b2ee13b8.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.523e65a94da2ee5c84.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.53d61c44d1fa312731.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.5458132f2cbbf90946.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.55e51e021b6ab930e5.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.5629ce0664760454f9.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.571b359956120fe526.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.5843ec7612330a9750.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.59f9d143a387552f7b.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.60002f2fc2cf15904a.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.61264d2ce4177ad4f5.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.620a09d0f5b3f048ae.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.633d9fd83e8445fe75.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.64fc762e7d40e85106.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.650c721f9fbc22b441.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.66d5b699bdca0d625b.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.67ad53a1d355e1b6df.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.68530b9b110ba8613c.png",
            "https://simp6.jpg5.su/images3/Kitty.Lever.7733e240f616519e7c.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.76cd42b8fa9ab903a0.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.75034723bf7370e35e.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.7462d0d2176deb4d7a.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.7348dea4ced2eb22d7.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.724ceef3078aa9b4df.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.712f2cffd239259762.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.70f8db76104f698a81.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.6903ab8d4293680ab1.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.81bf9689c4acd74427.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.80011b50b1c7857e15.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.7968a5b886101214e5.jpg",
            "https://simp6.jpg5.su/images3/Kitty.Lever.78e2817d658f85c26a.jpg",	
            "https://simp6.selti-delivery.ru/images3/opheliamillaiss_1754935282_3696987564710833402_268075649733565ccd9afc65a.jpg",
            "https://simp6.selti-delivery.ru/images3/harley_haisley_1755014114_3697648855471565221_82045342285516fa7dd5a51121.jpg",
            "https://simp6.selti-delivery.ru/images3/harley_haisley_1755014114_3697648855463159088_82045342286d988bd8475114c8.jpg",
            "https://simp6.selti-delivery.ru/images3/harley_haisley_1755014114_3697648855395988753_8204534228960bcc3391e325b2.jpg",
            "https://simp6.selti-delivery.ru/images3/karinascherzer_1755186468_3699094666121374443_28377567459330593be1fe1877f.jpg",
            "https://simp6.selti-delivery.ru/images3/karinascherzer_1755186468_3699094666297542959_2837756745997ac9f99397638a5.jpg",
            "https://simp6.selti-delivery.ru/images3/karinascherzer_1755186468_3699094666121544002_28377567459be9474d33bd11f65.jpg",
            "https://simp6.selti-delivery.ru/images3/maerynlong_1755117931_3698519731402531307_5009063389f2e68b834f9152.jpg",
            "https://simp6.selti-delivery.ru/images3/stellajones_1754851175_3696282025518750921_1370527420608a1a9e56301eb99.jpg",
            "https://simp6.selti-delivery.ru/images3/efrat_elmalich_1755167337_3698934182947360409_30801309773f90c3f81d84a9892.jpg",
            "https://simp6.selti-delivery.ru/images3/olivia.ponton_1754935100_3696986036266413346_1527715602afcb5d3907884cac.jpg",
            "https://simp6.selti-delivery.ru/images3/bikinibibleuk_1755328050_3700282338403446232_33639445949122482eb57ea81c9.jpg",
            "https://simp6.selti-delivery.ru/images3/bikinibibleuk_1755328050_3700282338403677617_33639445949847f1b3b6c683ba2.jpg",
            "https://simp6.selti-delivery.ru/images3/theanyalacey_1755095700_3697975776154924421_694741033667979335b8fddfd79.jpg",
            "https://simp6.selti-delivery.ru/images3/theanyalacey_1755095700_3697975776213616877_694741033667dfcd1c2d5993ddc.jpg",
            "https://simp6.selti-delivery.ru/images3/theanyalacey_1755095700_3697975776154811448_694741033666882a1d8e4ff921e.jpg",
            "https://simp6.selti-delivery.ru/images3/theanyalacey_1755095700_3697975776364538669_694741033665d06a2bb616da6ef.jpg",
            "https://simp6.selti-delivery.ru/images3/itszoyevans_1755288156_3699947681724698445_566754557646d85e3f237c42c4d.jpg",
            "https://simp6.selti-delivery.ru/images3/itszoyevans_1755288156_3699947681892426498_566754557648f616dafdd0ec6c8.jpg",
            "https://simp6.selti-delivery.ru/images3/wettmelons_1755319578_3700211272321873186_46224902083c17302c2fd2ee6a6.jpg",
            "https://simp6.selti-delivery.ru/images3/olivia.ponton_1755015074_3697656904471252197_1527715602f7d52e79919b4a75.jpg",
            "https://simp6.selti-delivery.ru/images3/olivia.ponton_1755015074_3697656904479541432_152771560246138d144d45246e.jpg",
            "https://simp6.selti-delivery.ru/images3/olivia.ponton_1755015074_3697656904471145059_1527715602008116cf54385a91.jpg",
            "https://simp6.selti-delivery.ru/images3/theanyalacey_1754847300_3696235542354353439_694741033664128a89076432fde.jpg",
            "https://simp6.selti-delivery.ru/images3/theanyalacey_1754847300_3696235542429908873_69474103366075c484fb0b05bd6.jpg",
            "https://simp6.selti-delivery.ru/images3/theanyalacey_1754847300_3696235542345950886_69474103366e2d694a738cd486c.jpg",
            "https://simp6.selti-delivery.ru/images3/theanyalacey_1754847300_3696235542345999377_694741033668c1a673918055540.jpg",
            "https://simp6.selti-delivery.ru/images3/wolfiecindy_1755099000_3698168012547927884_2036904572181c4c35dccbb8f.jpg",
            "https://simp6.selti-delivery.ru/images3/rosiehuess_1755200490_3699212284976589319_60847521966d26b847bda2a93b0.jpg",
            "https://simp6.selti-delivery.ru/images3/didiniav_1755265988_3699761724815230252_535815204754710684b6a53e304.jpg",
            "https://simp6.selti-delivery.ru/images3/didiniav_1755265988_3699761724815146564_53581520475b2271c34345c1d72.jpg",
            "https://simp6.selti-delivery.ru/images3/didiniav_1755265988_3699761724815119336_53581520475b2c7d38ece0a14d2.jpg",
            "https://simp6.selti-delivery.ru/images3/edengross_1755205482_3699254164657422562_5650266011949058ca9c1f85b40.jpg",
            "https://simp6.selti-delivery.ru/images3/edengross_1755205482_3699254164657530327_5650266011907742923ad30f66b.jpg",
            "https://simp6.selti-delivery.ru/images3/edengross_1755205482_3699254164523168426_56502660119b3088e65ce464643.jpg",
            "https://simp6.selti-delivery.ru/images3/cindyprado_1755222922_3699400459622648707_76388750df60558e0a921e2.jpg",
            "https://simp6.selti-delivery.ru/images3/cindyprado_1755222922_3699400459488563786_7638875ff07566dd09f89a3.jpg",
            "https://simp6.selti-delivery.ru/images3/cindyprado_1755222922_3699400459622601747_7638875a5979abc2ff0a5a7.jpg",
            "https://simp6.selti-delivery.ru/images3/cindyprado_1755222922_3699400459698159208_7638875c347ff43c644cf39.jpg",
            "https://simp6.selti-delivery.ru/images3/thekinsleywyatt_1755290699_3699969014257076872_5591998709fb3fa40af655be62.jpg",
            "https://simp6.selti-delivery.ru/images3/thekinsleywyatt_1755290699_3699969014374410029_5591998709c1c5be26ca7f039d.jpg",
            "https://simp6.selti-delivery.ru/images3/miamastrov_1755311710_3700145266931139082_2463238908ebd9427563a6487.jpg",
            "https://simp6.selti-delivery.ru/images3/miamastrov_1755311710_3700145266922721721_246323890ff59ce2fdd8c71b4.jpg",
            "https://simp6.selti-delivery.ru/images3/miamastrov_1755311710_3700145266922768658_246323890765fc4fda5be99f6.jpg",
            "https://simp6.selti-delivery.ru/images3/miamastrov_1755311710_3700145266939461881_2463238902fdeba33a28c3367.jpg",
            "https://simp6.selti-delivery.ru/images3/ninapark_1755196089_3699175368222421449_291771283bb7fefcd623ab7d.jpg",
            "https://simp6.selti-delivery.ru/images3/julia.hatch_1755290115_3699964117497779451_25385905670ce63684bc23661.jpg",
            "https://simp6.selti-delivery.ru/images3/nicolesahebi_1755283337_3699907258625560298_30759787482776cdb2ed6125b.jpg",
            "https://simp6.selti-delivery.ru/images3/nicolesahebi_1755283337_3699907258625659209_3075978747542059c03f7646f.jpg",
            "https://simp6.selti-delivery.ru/images3/nicolesahebi_1755283337_3699907258609037113_3075978743edd4775f39e99de.jpg",
            "https://simp6.selti-delivery.ru/images3/nicolesahebi_1755283337_3699907258625817778_307597874cbac382448c51823.jpg",
            "https://simp6.selti-delivery.ru/images3/nicolesahebi_1755283337_3699907258608829501_3075978740a5102401d2a5397.jpg",
            "https://simp6.selti-delivery.ru/images3/nicolesahebi_1755283337_3699907258608915733_307597874c44c0b97fc175451.jpg",
            "https://simp6.selti-delivery.ru/images3/nicolesahebi_1755283337_3699907258617249223_307597874d747e8704f9f5934.jpg",
            "https://simp6.selti-delivery.ru/images3/nicolesahebi_1755283337_3699907258617204264_307597874-13555940ee60146ad.jpg",
            "https://simp6.selti-delivery.ru/images3/nicolesahebi_1755283337_3699907258617204264_307597874bc561cb281fbb2b3.jpg",
            "https://simp6.selti-delivery.ru/images3/laura_martiin_1753886089_3688186297269476623_196090592971aaee4337884162.jpg",
            "https://simp6.selti-delivery.ru/images3/sadieemckennaa_1755311112_3700140253352970149_6006082051eff70f5aeb885329.jpg",
            "https://simp6.selti-delivery.ru/images3/queenkalin_1755289038_3699955081450650886_50450770487a574c66d21e4bf12.jpg",
            "https://simp6.selti-delivery.ru/images3/queenkalin_1755289038_3699955081450804666_504507704879b320edf810987ef.jpg",
            "https://simp6.selti-delivery.ru/images3/queenkalin_1755289038_3699955081467585031_504507704870e13bda3d688daf6.jpg",
            "https://simp6.selti-delivery.ru/images3/skilah_1755298900_3700037808409917804_415839508a1d845ca6bedd486.jpg",
            "https://simp6.selti-delivery.ru/images3/skilah_1755298900_3700037808108024030_4158395082cfe5ee9a65fabb0.jpg",
            "https://simp6.selti-delivery.ru/images3/skilah_1755298900_3700037808116355159_415839508f482daa72b9acfbd.jpg",
            "https://simp6.selti-delivery.ru/images3/skilah_1755298900_3700037808242216660_41583950889f7aa4775c0d74f.jpg",
            "https://simp6.selti-delivery.ru/images3/skilah_1755298900_3700037808242081168_41583950808c140deec34e846.jpg",
            "https://simp6.selti-delivery.ru/images3/minnarosaweber_1755198492_3699195530575894074_232367838062fe6268f0cfe91f.jpg",
            "https://simp6.selti-delivery.ru/images3/minnarosaweber_1755198492_3699195530575925380_2323678380e45342464d25c943.jpg",
            "https://simp6.selti-delivery.ru/images3/minnarosaweber_1755198492_3699195530575942260_23236783807fe888eff6181718.jpg",
            "https://simp6.selti-delivery.ru/images3/minnarosaweber_1755198492_3699195530575872812_2323678380eac442ba9c6b938d.jpg",
            "https://simp6.selti-delivery.ru/images3/minnarosaweber_1755198492_3699195530835957198_232367838035666dc2a8ee432f.jpg",
            "https://simp6.selti-delivery.ru/images3/aecemydn_1754594238_3694126675878063100_50099918501fd3621974412a0d9.jpg",
            "https://simp6.selti-delivery.ru/images3/bruletova__1754907257_3696752473384490380_2122662775364730b26dcec33f.jpg",
            "https://simp6.selti-delivery.ru/images3/bruletova__1754907257_3696752473678142846_21226627759a6a51443769b564.jpg",
            "https://simp6.selti-delivery.ru/images3/bruletova__1754907257_3696752473392947213_21226627758ad13d3695a481ac.jpg",
            "https://simp6.selti-delivery.ru/images3/freyatidy_1754929332_3696937648224522303_305545336aba685f63ee1eaf6.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1755246300_3699360322179757474_286221924dc80c4c32010e621.jpg",
            "https://simp6.selti-delivery.ru/images3/savannahraedemers_1755099754_3698367254916290668_230059117046b6276080986f2.jpg",
            "https://simp6.selti-delivery.ru/images3/americawisot_1753543170_3685309681316884286_68790372988b20ca1cf0eeb483.jpg",
            "https://simp6.selti-delivery.ru/images3/americawisot_1753543170_3685309681518063693_6879037298d8393352334a6e30.jpg",
            "https://simp6.selti-delivery.ru/images3/gracieabrams_1755177193_3699016860726340430_25785037771c9514d12caeaa5.jpg",
            "https://simp6.selti-delivery.ru/images3/bruletova__1755101920_3698385420512504953_2122662775d4846ce5033fda3a.jpg",
            "https://simp6.selti-delivery.ru/images3/bruletova__1755101920_3698385420504008563_21226627759a3d8e75a2da6e4d.jpg",
            "https://simp6.selti-delivery.ru/images3/bruletova__1755101920_3698385420512503921_2122662775f45fd4f3c2244797.jpg",
            "https://simp6.selti-delivery.ru/images3/bruletova__1755101920_3698385420495857049_2122662775b82eee29ba62acf3.jpg",
            "https://simp6.selti-delivery.ru/images3/anokhina_elizabeth_2007_1755197747_3699189275047998761_8372069527fd655b890a22c7c6.jpg",
            "https://simp6.selti-delivery.ru/images3/melisayanik_1754842747_3696211325944409945_7028557070e352e335a6b788a.jpg",
            "https://simp6.selti-delivery.ru/images3/kingsephi_1755187397_3699102454232077648_2294029348a5faf4086dec6b86.jpg",
            "https://simp6.selti-delivery.ru/images3/martineakersveen_1755084944_3698243020378264495_1898646256e399140efd1288.jpg",
            "https://simp6.selti-delivery.ru/images3/kyla.doddsss_1755196606_3699179706424628220_557015814795e7ec01858a3bf8.jpg",
            "https://simp6.selti-delivery.ru/images3/hallejolene_1754341454_3692006171197579196_13662048367b37078bc54fb20d.jpg",
            "https://simp6.selti-delivery.ru/images3/savannahraedemers_1755215069_3699334588480993709_2300591172d9b95142000de67.jpg",
            "https://simp6.selti-delivery.ru/images3/irelandklee_1755215571_3699338794886492412_910896022c4d8efc151bbb9a3.jpg",
            "https://simp6.selti-delivery.ru/images3/olivia.ponton_1755201438_3699220244146543734_1527715602bec9a2c0e14c5d15.jpg",
            "https://simp6.selti-delivery.ru/images3/talissasmalley__1755060246_3698035834369053308_89067969836cff106945d1ad51.jpg",
            "https://simp6.selti-delivery.ru/images3/frankiebstark_1755023111_3697724322661000078_4985881409e4b3e75545497c1.jpg",
            "https://simp6.selti-delivery.ru/images3/parispaasch11_1755136998_3698679679292776307_6128973138044d314ee7e1f78f3.jpg",
            "https://simp6.selti-delivery.ru/images3/charlyjordan_1754861765_3696370858328809762_17721201fd29f0ccfc0c66cc.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1748045654_3639193175852153645_28622192479e6933295f09e60.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1748045654_3639193175852133959_286221924bc5f39cd003cb2d7.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1748045654_3639193175860582529_28622192416a91a0d5a7c30ff.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1748536892_3643313976569641319_286221924eb02f967db7d80b2.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1748045654_3639193175852310243_286221924b9ac059ad906f928.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1748536892_3643313976620083685_286221924f0168f0ae4e41edd.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1749315458_3649845065421228878_286221924ca5014b3dea54a04.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1748536892_3643313976569526716_2862219242d05209e843d93bc.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1749315458_3649845065421380124_2862219242990febc7b51755c.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1748536892_3643313976611560451_286221924d1c337c0eceec9af.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1749315458_3649845065337275072_28622192489b3d592aaabac4f.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1749844559_3654283480542313644_286221924999f36024ecdb99f.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1749844559_3654283480248783258_28622192435b6147f641d1d02.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1750621543_3660801297305678031_2862219244301d8103f7a7d0b.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1749844559_3654283480248658033_2862219246555ca982cbf9845.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1750621543_3660801297297301396_2862219249eb2a80005c19b97.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1749708000_3652895008413721815_286221924c8fafddef0d96858.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1749844559_3654283480248656124_286221924d45445c8214606a1.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1750621543_3660801297288910465_286221924a86a377fa3e53dc8.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1750097200_3656402788766943286_286221924dcbb25c5986eacda.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1750183200_3656588415767669781_2862219249a931ef5be8beceb.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1749844559_3654283480240397897_2862219243ba87a6405abcb6f.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1749708000_3652895008699133818_2862219244b3af6da6486fb7c.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1750621543_3660801297297439215_2862219245c884fe64c69e55e.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1750675285_3661252116383633342_286221924b8e89be8ccc689d7.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1750097200_3656402788766866727_286221924f5dc22b533624df4.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1750781239_3662140927242303847_2862219244e8e3069146fb33d.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1750183200_3656588415767645386_286221924f3730d7b64383a1d.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1749844559_3654283480248654643_2862219242b2de54e4f56f6ec.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1750621543_3660801297297297950_286221924b94d5e30747eb63b.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1750675285_3661252116383725532_286221924a6d29edc2f5095d2.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1750097200_3656402788766891136_28622192417a3e3519455a2c0.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1750781239_3662140927233840919_28622192449b08baf4a5da831.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1750183200_3656588416086427638_286221924e17b2fa0d2d97c09.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1750621543_3660801297297231746_2862219246b0da3e7b7f3903d.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1750675285_3661252116391969201_28622192441250b0fe2a2d181.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1750781239_3662140927242386779_2862219248227922cefeb7d7f.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1751696156_3669815804958925952_286221924d4b41821bcf63f94.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1751696156_3669815804959129342_28622192470a2d5c2b3a8a4dd.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1751494513_3668124297679889904_2862219243682a5bfc690b9b7.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1751696156_3669815804958883779_28622192415455197f7c76f5d.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1751494513_3668124297864422042_286221924348d966582f7d7b8.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1751696156_3669815804959054165_2862219249e08384c87eb5449.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1753798639_3687452705505362207_286221924bc6ace374901a158.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1753798639_3687452705614364248_2862219246f3735628b70344a.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1753798639_3687452705480091136_286221924f5ebbfec8e9c44b9.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1753798639_3687452705505318242_286221924c162c871bb35b447.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1753798639_3687452705488400023_286221924162f6b21ad6c00f5.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1754412588_3692602890849993700_286221924a8c051a223e5011a.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1754412588_3692602890849985217_286221924989d8ec6d7b4b3ed.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1754672238_3694780989972806107_2862219246909a6c0ef34e7e6.jpg",
            "https://simp6.selti-delivery.ru/images3/darivo__1754672238_3694780989905824042_286221924103a409005cba1e0.jpg",
            "https://simp6.selti-delivery.ru/images3/siennaschmidt_1754234973_3691112942948132969_153605991408f5b5198ac90e8f.jpg",
            "https://simp6.selti-delivery.ru/images3/siennaschmidt_1754234973_3691112942922966373_1536059914047976b62a7282ab.jpg",
            "https://simp6.selti-delivery.ru/images3/siennaschmidt_1754234973_3691112942939745006_1536059914cebdebb067f162e4.jpg",
            "https://simp6.selti-delivery.ru/images3/siennaschmidt_1754234973_3691112942948112474_1536059914193ebac159976f9b.jpg",
            "https://simp6.selti-delivery.ru/images3/siennaschmidt_1754234973_3691112942939865820_1536059914aa5197e4658298e0.jpg",
            "https://simp6.selti-delivery.ru/images3/irelandklee_1754708359_3695083989867409641_9108960220c71a42ca120033e.jpg",
            "https://simp6.selti-delivery.ru/images3/shay.baradut_1754836260_3696156907064739654_415343982912eb5012dccd7279.jpg",
            "https://simp6.selti-delivery.ru/images3/shay.baradut_1754836260_3696156907274251990_41534398298248db874b5e540d.jpg",
            "https://simp6.selti-delivery.ru/images3/shay.baradut_1754836260_3696156907047860475_41534398298c540e1f8c46e7ea.jpg",
            "https://simp6.selti-delivery.ru/images3/skilah_1754433356_3692777101150740233_4158395083c62862d56d96271.jpg",
            "https://simp6.selti-delivery.ru/images3/skilah_1754433356_3692777101150677006_415839508c617dfcab3302255.jpg",
            "https://simp6.selti-delivery.ru/images3/skilah_1754433356_3692777101150841529_415839508a2b63c6e6da0c8d1.jpg",
            "https://simp6.selti-delivery.ru/images3/itsandreabotez_1754765797_3695565823013421785_504816370f2e5ac0093ae8843.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedelyyy_1754409927_3692580562253660081_614573853849fd84a6c141c8228.jpg",
            "https://simp6.selti-delivery.ru/images3/addy_kate_1752077190_3673012147254166789_63529346415c525948365d09e.jpg",
            "https://simp6.selti-delivery.ru/images3/addy_kate_1752289551_3674793564060053160_635293464be21b5b204789d00.jpg",
            "https://simp6.selti-delivery.ru/images3/addy_kate_1752621278_3677576293084395579_635293464863c4632da47ed9b.jpg",
            "https://simp6.selti-delivery.ru/images3/addy_kate_1752621278_3677576293084436802_635293464924dec8cdc56f5e3.jpg",
            "https://simp6.selti-delivery.ru/images3/addy_kate_1752621278_3677576293076145231_635293464f8e8c72ede399352.jpg",
            "https://simp6.selti-delivery.ru/images3/addy_kate_1752621278_3677576293084365371_635293464d7dc12628cdf59fc.jpg",
            "https://simp6.selti-delivery.ru/images3/addy_kate_1753906558_3688357998218358539_635293464c6e551293d579307.jpg",
            "https://simp6.selti-delivery.ru/images3/addy_kate_1752884826_3679787089633835589_635293464ff3ea014471a1f87.jpg",
            "https://simp6.selti-delivery.ru/images3/addy_kate_1752884826_3679787089633943979_63529346467decbd3fa555b24.jpg",
            "https://simp6.selti-delivery.ru/images3/addy_kate_1752884826_3679787089642158285_63529346488451f86c624c435.jpg",
            "https://simp6.selti-delivery.ru/images3/stasr0sa_1741404889_3583486403251082503_215750687754344af354455425.jpg",
            "https://simp6.selti-delivery.ru/images3/stasr0sa_1754522121_3693521719572162508_2157506877fb589244848fa75f.jpg",
            "https://simp6.selti-delivery.ru/images3/stasr0sa_1754522121_3693521719689542780_2157506877179c4ae7f69faff4.jpg",
            "https://simp6.selti-delivery.ru/images3/stasr0sa_1754522121_3693521719849086565_21575068778ea4bd28a66284a0.jpg",
            "https://simp6.selti-delivery.ru/images3/stasr0sa_1754522121_3693521719563820661_21575068770e94b5b1e3694984.jpg",
            "https://simp6.selti-delivery.ru/images3/thelauren111_1754167509_3690547012352254189_689717129973139e82f01bcdc28.jpg",
            "https://simp6.selti-delivery.ru/images3/kelseysoles_1754169525_3690563924518427444_17706802-1cef638780aaec63c.jpg",
            "https://simp6.selti-delivery.ru/images3/sarahvfit_1753924366_3688507380920966427_418776095182110d10a9a3f89e3.jpg",
            "https://simp6.selti-delivery.ru/images3/mandi.bagley_1753982183_3688992390116341960_15783503130-1fb7182088aa82b06.jpg",
            "https://simp6.selti-delivery.ru/images3/alice__briggs_1752752949_3678680828698690567_14197397333e602779fb7c7825.jpg",
            "https://simp6.selti-delivery.ru/images3/alice__briggs_1752752949_3678680828707243565_1419739733ad77914b2981a3d5.jpg",
            "https://simp6.selti-delivery.ru/images3/polinamalinovskaya_1753865400_3688012737430135823_7883249991ed6f2c96014deeb.jpg",
            "https://simp6.selti-delivery.ru/images3/polinamalinovskaya_1753865400_3688012737438505688_788324999fa7175645374c978.jpg",
            "https://simp6.selti-delivery.ru/images3/polinamalinovskaya_1753865400_3688012737731975487_788324999-1310c515ffcedbfa5.jpg",
            "https://simp6.selti-delivery.ru/images3/miabrown__1753549047_3685358978431501163_111040103e7b5979a808148c.jpg",
            "https://simp6.selti-delivery.ru/images3/polinamalinovskaya_1753865400_3688012737731975487_7883249999a320ef41e772d80.jpg",
            "https://simp6.selti-delivery.ru/images3/shay.baradut_1753442022_3684461188389947429_41534398292f5b973908127339.jpg",
            "https://simp6.selti-delivery.ru/images3/itsbabytana_1753563668_3685481629562225263_540462742465d6e7d50d5c968.jpg",
            "https://simp6.selti-delivery.ru/images3/alina_enero_1753464056_3684646020529128777_1024769182d16c887a22494f55.jpg",
            "https://simp6.selti-delivery.ru/images3/zoeklp_1752679193_3678062117714502251_22782639036dd1bd9e80b1171f.jpg",
            "https://simp6.selti-delivery.ru/images3/shay.baradut_1753547703_3685347708781014544_4153439829ed629587326dc0d9.jpg",
            "https://simp6.selti-delivery.ru/images3/xhesikagjinaj_1752056911_3672842035527111262_2898508217022fc0949aa7a0a0.jpg",
            "https://simp6.selti-delivery.ru/images3/_m_gramovich_1752387025_3675611236982419078_36798296339c10e00cf75d0dd62.jpg",
            "https://simp6.selti-delivery.ru/images3/thebuffunicornn_1753370910_3683864661784466972_70123155063613c13bce944cf0b.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedely_1753377518_3683920086464643712_26531627896f4d39c0a911ab5.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedely_1753377518_3683920086464676692_2653162789df11bf7f2be2ecc.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedely_1753377518_3683920086472941368_26531627810544aacc848f256.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedely_1753377518_3683920086464526899_2653162781cc01c277a0aa9d7.jpg",
            "https://simp6.selti-delivery.ru/images3/martynabalsam_1710480306_3324072195864060842_7102088980b5d1358c1bbeafe.jpg",
            "https://simp6.selti-delivery.ru/images3/martynabalsam_1714737918_3359787631196442985_71020889860af01fe0a16fbe7.jpg",
            "https://simp6.selti-delivery.ru/images3/martynabalsam_1732140402_3505770248838056036_7102088989e7372d40a8e98ae.jpg",
            "https://simp6.selti-delivery.ru/images3/martynabalsam_1732140402_3505770248838113593_710208898e90d66159fccad87.jpg",
            "https://simp6.selti-delivery.ru/images3/martynabalsam_1746728814_3628146722644162608_71020889809558b6aaa6ab429.jpg",
            "https://simp6.selti-delivery.ru/images3/martynabalsam_1746728814_3628146722627132753_710208898bf79aef2385e9980.jpg",
            "https://simp6.selti-delivery.ru/images3/martynabalsam_1747327113_3633165614311446381_71020889823729a3fa8cf2f0f.jpg",
            "https://simp6.selti-delivery.ru/images3/martynabalsam_1747947990_3638373910563769852_71020889844798c7061ce9303.jpg",
            "https://simp6.selti-delivery.ru/images3/martynabalsam_1750000529_3655591856040939841_71020889851de5938ce0ffca8.jpg",
            "https://simp6.selti-delivery.ru/images3/martynabalsam_1750364852_3658648017624514516_710208898d838aafcd4d3ff6e.jpg",
            "https://simp6.selti-delivery.ru/images3/martynabalsam_1751987365_3672258637803435211_710208898e4709d6514e4bce4.jpg",
            "https://simp6.selti-delivery.ru/images3/martynabalsam_1752327278_3675110035108702896_7102088983f9b494b455f97e2.jpg",
            "https://simp6.selti-delivery.ru/images3/martynabalsam_1752155727_3673670962980772941_710208898cf2a496f56cd6bdc.jpg",
            "https://simp6.selti-delivery.ru/images3/martynabalsam_1752155727_3673670962989182342_710208898c618ae17e40eff6b.jpg",
            "https://simp6.selti-delivery.ru/images3/9760c559-4c65-4e26-b0a4-6ff90ce0eae0b9541d35ed15150f.jpg",
            "https://simp6.selti-delivery.ru/images3/emily.feld_1753260344_3682937167464301092_34615323445562008fede1bd8b.jpg",
            "https://simp6.selti-delivery.ru/images3/emily.feld_1753260344_3682937167631883490_3461532344530001524d2aa645.jpg",
            "https://simp6.selti-delivery.ru/images3/iris.vallaranii_1753194633_3682385938466736011_47072578159b7165c8c7c640dc5.jpg",
            "https://simp6.selti-delivery.ru/images3/rilleyymitchell_1753278424_3683088825442603404_420437439765d1eb395dc49254.jpg",
            "https://simp6.selti-delivery.ru/images3/rilleyymitchell_1753278423_3683088825526256704_4204374397916022fb352bd26b.jpg",
            "https://simp6.selti-delivery.ru/images3/rilleyymitchell_1753278423_3683088825442629834_4204374397687f3343f3890805.jpg",
            "https://simp6.selti-delivery.ru/images3/siennaschmidt_1752770761_3678830247995019016_15360599146686a788438bd78c.jpg",
            "https://simp6.selti-delivery.ru/images3/hopie.schlenker_1752789388_3678986498537261120_301937279060a902a88f3e66e.jpg",
            "https://simp6.selti-delivery.ru/images3/juliaernst_1753036799_3681061931943922893_826214700935dbbc0a471f543.jpg",
            "https://simp6.selti-delivery.ru/images3/millieleer_1752779350_3678902295777518087_1649810359690b032a812ff8fb.jpg",
            "https://simp6.selti-delivery.ru/images3/reneeebeller_1752767776_3678805203000605849_320936424605ee22cebe079db47.jpg",
            "https://simp6.selti-delivery.ru/images3/bikinibibleuk_1753205214_3682474699057785752_3363944594942991b61d58c7384.jpg",
            "https://simp6.selti-delivery.ru/images3/bikinibibleuk_1753205214_3682474699057556575_336394459496be4c036172a1e35.jpg",
            "https://simp6.selti-delivery.ru/images3/bikinibibleuk_1753205214_3682474699057723553_336394459493ae2c32cec8c4e37.jpg",
            "https://simp6.selti-delivery.ru/images3/bikinibibleuk_1753205214_3682474699057594160_336394459492b1253988e1b78b4.jpg",
            "https://simp6.selti-delivery.ru/images3/little.warren__1753124359_3681796440273250736_5310715852128a9fec068fa17f8.jpg",
            "https://simp6.selti-delivery.ru/images3/noordabashh_1753128693_3681832796395213328_5910415467af89fc2b39975dae.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedely_1752972199_3680520026869062339_2653162784c09b303718791fd.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedely_1752972199_3680520027003239063_265316278cd73ea11bf494b53.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedelyyy_1752703079_3678262487800926199_6145738538402091cee44238f76.jpg",
            "https://simp6.selti-delivery.ru/images3/ellachristo_1752846720_3679467436874487511_30635971686257c6d44e34b2c75.jpg",
            "https://simp6.selti-delivery.ru/images3/bruletova__1753175537_3682225752459219140_2122662775232395b0bfb9ddc3.jpg",
            "https://simp6.selti-delivery.ru/images3/bruletova__1753175537_3682225752174201464_2122662775daa027f0a36dceac.jpg",
            "https://simp6.selti-delivery.ru/images3/thebuffunicornn_1744901615_3612819062436203144_701231550639bfa0bb75bc3d621.jpg",
            "https://simp6.selti-delivery.ru/images3/thebuffunicornn_1744901615_3612819062385810178_701231550639ed9f972e959a8fd.jpg",
            "https://simp6.selti-delivery.ru/images3/thebuffunicornn_1744901615_3612819062394429662_7012315506363fe7ce0025a9462.jpg",
            "https://simp6.selti-delivery.ru/images3/charleenweiss_1752588803_3677303870765208136_40718143529f0aebe13fb41d.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedely_1752599036_3677389708874621244_265316278a05938d72c49241c.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedely_1752599036_3677389708916447243_2653162785a66cb716084c0f1.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedely_1752599036_3677389708924925335_265316278d47eaf79d43c9cbd.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedely_1752599036_3677389708925016797_26531627851cd905ea9c2cb28.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedely_1752599036_3677389708874626539_265316278709e0181aca28f88.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedely_1752599036_3677389708924940377_2653162786e14c8f974cfbffb.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedely_1752599036_3677389708916588915_26531627818400d905a46891e.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedely_1752599036_3677389708924940529_265316278a8c59b8c5c3360c0.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedely_1752599036_3677389708908260259_2653162783fb6a52680db2a6a.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedely_1752599036_3677389708916632508_2653162784c7e14c92e5a20a4.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedely_1752599036_3677389709067581188_265316278fd5ee98603a525d6.jpg",
            "https://simp6.selti-delivery.ru/images3/smashedely_1752599036_3677389708874634460_2653162785d9158ad56521bbe.jpg",
            "https://simp6.selti-delivery.ru/images3/lulu.broski_1749310748_3649805554516490692_26950999913b5958d38f34bd785.jpg",
            "https://simp6.selti-delivery.ru/images3/lulu.broski_1749310748_3649805554558252166_269509999135be645ab2145464c.jpg",
            "https://simp6.selti-delivery.ru/images3/lulu.broski_1749310748_3649805554658892103_26950999913f5b47a78ed8635a5.jpg",
            "https://simp6.selti-delivery.ru/images3/lulu.broski_1749310748_3649805554508041949_269509999138f0569d144494b9a.jpg",
            "https://simp6.selti-delivery.ru/images3/lulu.broski_1749310748_3649805554516478910_269509999130da9e2b660940e8c.jpg",
            "https://simp6.selti-delivery.ru/images3/ghostlifestyleapparel_1739815249_3570136371949294942_60891769504b065662235a2bfa2.jpg",
            "https://simp6.selti-delivery.ru/images3/ghostlifestyleapparel_1739815249_3570136332933040587_608917695049e50dc8c4ba916ed.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1740007975_3571768239044081265_4876300665886eaed0fd7122.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1740523784_3576095153841770222_487630063bcb1f66527c472d.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1740523784_3576095153699367928_4876300611e5327e5c7664b5.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1741109635_3581009629980458083_487630064b4909615ff3dd18.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1741109635_3581009630022416469_48763006a8f80ab6ef8222a8.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1741109635_3581009630106303907_48763006d1b19a21002d474d.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1741109635_3581009630064483578_4876300673551f29a10b7d63.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1741391515_3583374209562112817_48763006bac6d3e84293ab4f.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1741391515_3583374209578705072_487630069d67ebb0f7ff473d.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1741391515_3583374209578727779_487630068358324729166857.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1741391515_3583374209713007965_4876300650dcc34ba0094a68.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1741391515_3583374209746537883_487630067057ba68a9a2c016.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1741391515_3583374209771827710_487630068eaebc01cf4450a4.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1741391515_3583374209704544587_48763006d7b5b48b650fb048.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1741904235_3587675212982385823_48763006ee41dc24534f869f.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1741904235_3587675213007570290_48763006db34ef9e7da83336.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1741904234_3587675212697281647_4876300623a905b008f738e7.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1741904234_3587675212697295576_48763006da9cecb2b9a7fb9d.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1742242942_3590516497413625732_487630069c2bbaeef37059e4.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1742242942_3590516497422122741_48763006bf5cdf876dc2a17c.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1742242942_3590516497413722945_487630066600d22cf0f8b8b3.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1742242942_3590516497589845612_487630067ec9845e9a713fbb.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1742242942_3590516497723971028_4876300647c0e80e722b2461.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1742242942_3590516497413751428_487630065d4690b68f8734de.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1742242942_3590516497531048190_48763006ab4b4528dac34834.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1742242942_3590516497589987547_48763006c98859ca5b7ce226.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1742242942_3590516497531046734_48763006614247804363456d.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1742242942_3590516497715577629_487630068a775ed6359224d3.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1742242942_3590516497405382013_48763006c8616325f9978f27.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1742408222_3591902964777619890_48763006179b8efe904de984.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1742408222_3591902964542837830_48763006a384a178d71ae3a0.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1742594102_3593462242408315711_48763006d6391afa9196cf46.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1743105589_3597752908017705314_48763006-106fd46176d0ca4f9.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1743105589_3597752907875162331_48763006-11b5b709b1e2e2b78.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1743105589_3597752908143408163_48763006-1021d300c5d46cd47.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1743105589_3597752907874982791_48763006013e83b77cab59e6.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1743105589_3597752908017705314_48763006431d55cd91f68bc8.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1743266564_3599103257814779689_487630069b691748619e5a07.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1743266564_3599103257915534978_487630061c7ce1491fad6432.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1743977223_3605064698396731133_4876300628275d708ccbb38a.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1743977223_3605064698254210212_48763006169f2005c05818ca.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1743977223_3605064698262672379_4876300676c78c37d1adb9da.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1744398119_3608595433422458434_48763006b7773b168e520438.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1744398119_3608595433590335261_4876300689368d250729af12.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1744558860_3609943826432923879_48763006f64fa959d84083bd.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1744815405_3612095879801506443_48763006a60194470b0d9355.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1744925548_3613019829310858402_48763006b39a0027623494b6.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1746487799_3626124936029873819_48763006-159ae0776ce4a7bab.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1746487799_3626124936172516626_48763006-1b093eb01adf8d2de.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1746487799_3626124936172516626_487630068d37e4d4888cbc0a.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1746562646_3626752803323442248_4876300669c979ec591cda8c.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1746562646_3626752803415653336_4876300691b462e4868aef29.jpg",
            "https://simp6.selti-delivery.ru/images3/abigailwhhitee_1746562646_3626752803432339376_48763006b37b68569b0ab87b.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1744482727_3609305176722447303_30635971686d605a6036db5f091.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1744482727_3609305176714124767_30635971686d7868d147345d922.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1744482727_3609305176982561227_30635971686f064b6cf6bde7e58.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1744482727_3609305176714041816_306359716860595df58a9425c6a.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1744482727_3609305176714058675_30635971686c22b98cce8fd2a77.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1744482727_3609305176680510509_30635971686b4763f3e5a7d6830.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1744482727_3609305176982646442_3063597168645f4e790a971572b.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1744482727_3609305176714146790_306359716861c91dc2540e4b872.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1744552210_3609888040528647224_306359716868d0e9e91cad00e5a.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1744552210_3609888040570609115_30635971686a68d6e058f112bd2.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1744583212_3610148107213825218_30635971686fd40114eb6779664.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1744583212_3610148107540879015_306359716865261dfebae56bfb2.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1744583212_3610148107524024568_306359716869bef01f35cd73a0b.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1744583212_3610148107356289033_306359716861ca2019da4651f49.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1745237916_3615640156277030179_30635971686eb9839d4b7e41623.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1745237916_3615640156083973805_3063597168669fcdbbfe66b44cc.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1745237916_3615640156260106717_306359716868e245369db25be10.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1745410436_3617087363089706905_30635971686434233ab07e8b1a3.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1745410436_3617087363383532408_3063597168660df3c5fab1bf7e6.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1745410436_3617087363056230142_3063597168682fc34ecbb01dcab.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1745410436_3617087363089724710_3063597168679b4d9e89ec00387.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1745410436_3617087363073063758_306359716868b05aeaada124ad4.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1745410436_3617087363081411052_30635971686f7c8061cc5f5e081.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1745410436_3617087363081550216_306359716864658831eb71fd732.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1746442457_3625744583067427135_3063597168674cd266c898e430b.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1746103246_3622899071377024067_30635971686eab7555e2a75d080.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1746103246_3622899071377019725_306359716864eea0962324fc1c4.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1746103246_3622899071377190884_30635971686de0b46eabe2a1342.jpg",
            "https://simp6.selti-delivery.ru/images3/ella.christo__1746442457_3625744582949800374_306359716866eec920934fa625a.jpg",
            "https://simp6.selti-delivery.ru/images3/skilah_1746397020_3625363425129388946_415839508928d11609d731ff5.jpg",
            "https://simp6.selti-delivery.ru/images3/sofiamuse_1746471340_3625986873845394832_3429948035f62c67d75612e38d.jpg",
            "https://simp6.selti-delivery.ru/images3/sofiamuse_1746471340_3625986873669200788_3429948035b78de716d0ec3d59.jpg",
            "https://simp6.selti-delivery.ru/images3/sofiamuse_1746471340_3625986873820375675_3429948035c3fd677d5000e47c.jpg",
            "https://simp6.selti-delivery.ru/images3/sofiamuse_1725382695_3449082496797691279_3429948035c815d527574577a9.jpg",
            "https://simp6.selti-delivery.ru/images3/sofiamuse_1725996060_3454227776914680899_3429948035530972d4a651576a.jpg",
            "https://simp6.selti-delivery.ru/images3/sofiamuse_1726775065_3460762540790251548_34299480357b4d4793e028c23d.jpg",
            "https://simp6.selti-delivery.ru/images3/sofiamuse_1727464933_3466549570489262479_3429948035663aecb889cc27f4.jpg",
            "https://simp6.selti-delivery.ru/images3/sofiamuse_1728582585_3475925119108106368_34299480351c28ff6d294b0d1a.jpg",
            "https://simp6.selti-delivery.ru/images3/sofiamuse_1728582585_3475925118982133232_342994803592004050ba1fccab.jpg",
            "https://simp6.selti-delivery.ru/images3/sofiamuse_1728582585_3475925118990576676_3429948035dbedd90651c96727.jpg",
            "https://simp6.selti-delivery.ru/images3/sofiamuse_1737667652_3552136181712529874_34299480353f5fb1ec339cb42c.jpg",
            "https://simp6.selti-delivery.ru/images3/sofiamuse_1742051665_3588911949501537595_34299480355c53b923688461d5.jpg",
            "https://simp6.selti-delivery.ru/images3/sofiamuse_1744484994_3609324193139157716_34299480354bd55e91315e963a.jpg",
            "https://simp6.selti-delivery.ru/images3/sofiamuse_1744484994_3609324193130940649_3429948035139c381bbb606449.jpg",
            "https://simp6.selti-delivery.ru/images3/sofiamuse_1744484994_3609324193130978917_34299480350eb26602481108e4.jpg",
            "https://simp6.selti-delivery.ru/images3/sofiamuse_1744484994_3609324193231502887_342994803504995ffddeea1c4b.jpg",
            "https://simp6.selti-delivery.ru/images3/sofiamuse_1744484994_3609324193130816235_342994803554e5d684bd1109dd.jpg",
            "https://simp6.selti-delivery.ru/images3/sofiamuse_1745962016_3621714348768893962_342994803559b97df7ddd7c5a0.jpg",
            "https://simp6.selti-delivery.ru/images3/sofiamuse_1745962016_3621714348793969595_3429948035f25f1077d9aa5bdd.jpg"
        ]
        default_pic_url = Aria2c.pic_dwn_url # Get default from Aria2c settings
        chosen_url = None
        hero_image_path = Paths.HERO_IMAGE # Path where thumbnail will be saved

        # Assume 'thumbnail_urls' list is populated earlier (e.g., from Paths.list_hero)
        if thumbnail_urls: # Check if the random list exists and is not empty
            log.info("Choosing random thumbnail from list.")
            chosen_url = random.choice(thumbnail_urls)
            log.info(f"Randomly selected thumbnail URL: {chosen_url}")
        else:
            # Fallback to default if the random list is empty or not defined
            log.warning("Random thumbnail URL list is empty or not available. Falling back to default URL.")
            chosen_url = default_pic_url
        # --- End Always Random Choice ---

        # --- Download the chosen thumbnail (Your existing download logic) ---
        download_success = False # Flag to track if download worked
        if chosen_url:
            log.info(f"Attempting asynchronous download of thumbnail from: {chosen_url}")
            try:
                # Create a single session for potential multiple requests (though only one here)
                async with aiohttp.ClientSession() as session:
                    # Use a timeout for the request to prevent indefinite hangs
                    async with session.get(chosen_url, timeout=30) as response:
                        # Check if the request was successful (HTTP status 200 OK)
                        if response.status == 200:
                            # Open the destination file asynchronously for binary writing
                            async with aiofiles.open(hero_image_path, mode='wb') as f:
                                # Write the content chunk by chunk for memory efficiency
                                while True:
                                    chunk = await response.content.read(1024) # Read 1KB chunks
                                    if not chunk:
                                        break # Exit loop when download is complete
                                    await f.write(chunk)

                            # Verify file exists and has size after writing
                            # Ensure getSize is available in this scope (imported from helper likely)
                            if ospath.exists(hero_image_path) and getSize(hero_image_path) > 0:
                                download_success = True # Set flag on success
                                log.info(f"Successfully downloaded thumbnail to {hero_image_path} via aiohttp.")
                            else:
                                log.warning(f"Thumbnail file missing or empty after writing: {hero_image_path}")
                                # Attempt cleanup if write failed partially
                                try:
                                    if ospath.exists(hero_image_path): os.remove(hero_image_path)
                                except OSError as cleanup_err:
                                     log.warning(f"Could not remove partially written thumbnail: {cleanup_err}")
                        else:
                            # Log HTTP errors if the request failed
                            log.warning(f"Failed to download thumbnail. HTTP status: {response.status}. URL: {chosen_url}")

            # --- Specific Exception Handling for Async Download ---
            except aiohttp.ClientError as http_err:
                log.error(f"Network/HTTP error downloading thumbnail: {http_err}", exc_info=False)
            except asyncio.TimeoutError:
                 log.error(f"Timeout error downloading thumbnail from {chosen_url}")
            except Exception as dl_err:
                # Catch any other unexpected errors during download/write
                log.error(f"Generic exception downloading/writing thumbnail: {dl_err}", exc_info=True)
                # Attempt cleanup in case of generic error during write
                try:
                    if ospath.exists(hero_image_path): os.remove(hero_image_path)
                except OSError as cleanup_err:
                    log.warning(f"Could not remove thumbnail after generic error: {cleanup_err}")
            # --- End Specific Exception Handling ---

        else:
             # This else corresponds to 'if chosen_url:'
             log.warning("No chosen_url determined for thumbnail.")
        # --- End Asynchronous Download Logic ---

        # --- Set final thumbnail path (This logic remains the same) ---
        final_thumb_path = hero_image_path
        if not download_success:
            # Fallback if download failed or no URL was chosen
            log.warning(f"Thumbnail download failed or no URL. Checking/Using fallback thumbnail: {Paths.DEFAULT_HERO}")
            # Ensure Paths.DEFAULT_HERO points to a valid *local* file path
            if ospath.exists(Paths.DEFAULT_HERO):
                 final_thumb_path = Paths.DEFAULT_HERO
            else:
                 log.error(f"Fallback thumbnail {Paths.DEFAULT_HERO} also does not exist!")
                 final_thumb_path = None # No thumbnail available
        # --- End Thumbnail Handling ---

        # --- Initial Task Messages ---
        log.info("Sending initial task messages...")
        Messages.link_p = str(DUMP_ID)[4:] if str(DUMP_ID).startswith("-100") else str(DUMP_ID)
        try:
            # Send source links to dump chat
            MSG.sent_msg = await colab_bot.send_message(chat_id=DUMP_ID, text=src_text[0], disable_web_page_preview=True)
            if len(src_text) > 1:
                for lin in range(1, len(src_text)):
                    MSG.sent_msg = await MSG.sent_msg.reply_text(text=src_text[lin], quote=True, disable_web_page_preview=True)

            # Construct source link for status message
            Messages.src_link = f"https://t.me/c/{Messages.link_p}/{MSG.sent_msg.id}" if MSG.sent_msg and hasattr(MSG.sent_msg.chat, 'id') and MSG.sent_msg.chat.id != OWNER else getattr(MSG.sent_msg, 'link', '#')
            task_title = f"{type_display_name} {mode_display_name}{service_str}"
            Messages.task_msg += f"__[{task_title}]({Messages.src_link})__\n\n" # Prepend task context to status message base

            # Delete previous status message if it exists
            if MSG.status_msg: await MSG.status_msg.delete()

            # Determine which image to send (Custom > Downloaded/Fallback)
            img_to_send = Paths.THMB_PATH if BOT.Setting.thumbnail and ospath.exists(Paths.THMB_PATH) else final_thumb_path

            # Send initial status message with photo
            if not ospath.exists(img_to_send):
                 log.error(f"Thumbnail path to send does not exist: {img_to_send}. Attempting absolute fallback.")
                 img_to_send = Paths.DEFAULT_HERO # Use defined fallback path first
                 if not ospath.exists(img_to_send):
                       log.critical("FATAL: No valid thumbnail image found to send.")
                       MSG.status_msg = await colab_bot.send_message(chat_id=OWNER, text=Messages.task_msg + Messages.status_head + f"\n📝 __Initializing...__ (Thumbnail Error)" + sysINFO(), reply_markup=keyboard())
                 else:
                       MSG.status_msg = await colab_bot.send_photo( chat_id=OWNER, photo=img_to_send, caption=Messages.task_msg + Messages.status_head + f"\n📝 __Initializing...__" + sysINFO(), reply_markup=keyboard())
            else:
                 MSG.status_msg = await colab_bot.send_photo( chat_id=OWNER, photo=img_to_send, caption=Messages.task_msg + Messages.status_head + f"\n📝 __Initializing...__" + sysINFO(), reply_markup=keyboard())

        except Exception as msg_err:
            log.error(f"Error sending initial task messages: {msg_err}", exc_info=True)
            TaskError.state = True
            TaskError.text = f"Failed send status: {msg_err}"
            # Return early if status sending fails critically
            # No need to explicitly return, finally block handles cancellation if TaskError is set
            pass # Allow finally block to handle cancellation

        # --- Pre-checks (Size/Name) ---
        # Only run if no error has occurred yet
        if not TaskError.state:
            log.info("Running pre-checks (size/name)...")
            # Skip pre-calc/name guess for certain services or dir mode
            if not is_dir and selected_service not in ['nzbcloud', 'delta', 'bitso', 'ytdl', 'local']:
                 await calDownSize(BOT.SOURCE) # Only attempts GDrive/TG
                 if BOT.SOURCE: await get_d_name(BOT.SOURCE[0]) # Only attempts GDrive/TG/YTDL/Aria2
                 else: Messages.download_name = "Task_No_Sources"; log.warning("BOT.SOURCE empty.")
            elif not is_dir and selected_service in ['nzbcloud', 'delta', 'bitso']:
                 # Name/size handled later or manually provided
                 if MSG.status_msg: await MSG.status_msg.edit_caption(caption=Messages.task_msg + Messages.status_head + f"\n📝 __Waiting for downloader...__" + sysINFO(), reply_markup=keyboard())

        # --- Adjust Download Path for Zip Mode ---
        # Only if no error has occurred yet
        if not TaskError.state:
            if is_zip:
                zip_base_name = BOT.Options.custom_name if BOT.Options.custom_name else Messages.download_name if Messages.download_name else "Download"
                # Use original_Paths_down_path as the base for the zip subfolder
                Paths.down_path = ospath.join(original_Paths_down_path, clean_filename(zip_base_name))
                makedirs(Paths.down_path, exist_ok=True)
                log.info(f"Zip mode: Download target subfolder: {Paths.down_path}")
            else:
                Paths.down_path = original_Paths_down_path # Ensure it uses the base path if not zip

        # --- Execute Main Task ---
        # Only if no error has occurred yet
        if not TaskError.state:
            BotTimes.current_time = time() # Update time before starting main work
            is_ytdl_task = (selected_service == 'ytdl') or BOT.Mode.ytdl
            log.info(f"Starting main task execution: Mode={current_mode}, Service={selected_service}, is_ytdl={is_ytdl_task}")
            if current_mode != "mirror":
                await Do_Leech(BOT.SOURCE, is_dir, is_ytdl_task, is_zip, is_unzip, is_dualzip)
            else:
                await Do_Mirror(BOT.SOURCE, is_ytdl_task, is_zip, is_unzip, is_dualzip)

    except Exception as scheduler_err:
         log.error(f"Error within taskScheduler main try block: {scheduler_err}", exc_info=True)
         # Set error state if one hasn't been set already
         if not TaskError.state:
             TaskError.state = True
             TaskError.text = f"Scheduler Error: {scheduler_err}"
             # Don't call cancelTask here, finally block will handle it
    finally:
        # This block runs whether an exception occurred or not
        log.info("taskScheduler finished or encountered error. Entering finally block.")
        # Restore original download path if it was changed
        if Paths.down_path != original_Paths_down_path:
             Paths.down_path = original_Paths_down_path
             log.debug("Restored original Paths.down_path")

        # Check if an error occurred during the task
        if TaskError.state:
            log.warning(f"Task failed. Reason: {TaskError.text}. Initiating cancellation/cleanup.")
            # Call cancelTask only if it wasn't the source of the error itself
            # This check might be complex depending on specific errors caught above
            # A simple approach is to always call it if TaskError.state is True
            await cancelTask(f"Task Failed: {TaskError.text}")
        else:
            log.info("taskScheduler completed successfully (no TaskError set). Logs should be sent by Do_Leech/Do_Mirror.")
        # Note: SendLogs is called within Do_Leech/Do_Mirror on success.
        # cancelTask handles cleanup and status updates on failure.

        # Remove the task key from the running_tasks set so that
        # subsequent identical tasks can be scheduled.  Use a local
        # lookup to avoid NameError if the variable is not defined.
        try:
            running_tasks.discard(task_key)
        except Exception:
            pass


# --- NEW Do_Leech Function with Batch Processing ---
# --- Replace the ENTIRE Do_Leech function with this ---
async def Do_Leech(source, is_dir, is_ytdl, is_zip, is_unzip, is_dualzip):
    global BOT, TRANSFER, Paths, Messages, TaskError, log # Ensure log is accessible
    log.info(f"Do_Leech started. is_dir={is_dir}, is_ytdl(legacy)={is_ytdl}, is_zip={is_zip}, is_unzip={is_unzip}, is_dualzip={is_dualzip}")
    original_down_path = Paths.down_path # Store original base download path
    selected_service = BOT.Options.service_type
    overall_success = True # Track if all batches succeeded
    # Get the full list of filenames if provided manually
    full_filenames_list = BOT.Options.filenames if BOT.Options.filenames else []

    # --- Main Try Block for Do_Leech ---
    try:
        # --- Handle Directory Leech (No Batching) ---
        if is_dir:
            # <<< Keep your existing, working dir-leech logic here >>>
            # <<< Ensure it correctly sets TaskError.state on failure >>>
            # Example Structure (replace with your actual logic):
            log.info("Do_Leech: Directory mode selected.")
            source_path_item = source[0]
            log.info(f"Do_Leech: Processing directory/file {source_path_item}")
            process_source_path = source_path_item
            leech_target_path = None
            cleanup_after_leech = True

            if not ospath.exists(process_source_path):
                TaskError.state=True; TaskError.text=f"Dir-leech source missing: {process_source_path}"; raise Exception(TaskError.text) # Raise to exit via finally

            # Apply Zip/Unzip processing
            if is_zip:
                await Zip_Handler(process_source_path, True, False)
                if TaskError.state: raise Exception(TaskError.text)
                leech_target_path = Paths.temp_zpath
            elif is_unzip:
                await Unzip_Handler(process_source_path, False)
                if TaskError.state: raise Exception(TaskError.text)
                leech_target_path = Paths.temp_unzip_path
            elif is_dualzip:
                await Unzip_Handler(process_source_path, False)
                if TaskError.state: raise Exception(TaskError.text)
                await Zip_Handler(Paths.temp_unzip_path, True, True)
                if TaskError.state: raise Exception(TaskError.text)
                leech_target_path = Paths.temp_zpath
            else: # Normal leech for dir
                 if ospath.isdir(process_source_path):
                      leech_target_path = process_source_path
                      cleanup_after_leech = False
                 elif ospath.isfile(process_source_path):
                      # Copy single file logic... ensure it raises Exception on error
                      if not ospath.exists(Paths.temp_dirleech_path): makedirs(Paths.temp_dirleech_path, exist_ok=True)
                      try:
                           shutil.copy2(process_source_path, Paths.temp_dirleech_path)
                           leech_target_path = Paths.temp_dirleech_path
                           # ... set name/size ...
                      except Exception as copy_err:
                           log.error(f"Failed copy single file for dir-leech: {copy_err}")
                           TaskError.state = True; TaskError.text = f"Copy Error: {copy_err}"; raise Exception(TaskError.text)
                 else:
                      TaskError.state = True; TaskError.text = "Source path disappeared"; raise Exception(TaskError.text)

            # Call Leech handler
            if leech_target_path and ospath.exists(leech_target_path):
                 log.info(f"Do_Leech: Starting Leech handler for dir from path: {leech_target_path}")
                 await Leech(leech_target_path, cleanup_after_leech)
                 if TaskError.state: raise Exception(TaskError.text) # Raise if Leech failed
            elif not TaskError.state:
                 log.error(f"Processing failed or leech path missing for dir-leech: {leech_target_path}")
                 TaskError.state = True; TaskError.text = f"Dir processing error ({BOT.Mode.type})"; raise Exception(TaskError.text)
            # <<< End of example dir-leech logic >>>

        # --- Handle Link Modes with Batch Processing ---
        else:
            source_links = list(source) # Ensure it's a list
            batch_size = 1 # Process one link per batch
            total_links = len(source_links)
            manual_filenames_provided = bool(full_filenames_list)

            # Validate filename count if manual filenames were provided
            if manual_filenames_provided and len(full_filenames_list) != total_links:
                 log.error(f"Do_Leech Error: Initial filename count ({len(full_filenames_list)}) doesn't match link count ({total_links}).")
                 # Set error state and raise exception to exit via finally block
                 TaskError.state = True; TaskError.text = "Initial filename/link count mismatch."
                 raise Exception(TaskError.text)

            log.info(f"Do_Leech: Link mode selected. Processing {total_links} links in batches of {batch_size}.")

            # --- Start of Batch Loop ---
            for i in range(0, total_links, batch_size):
                # --- Start of Batch Processing Logic ---
                # Check 1: Check for critical errors *before* starting batch
                if TaskError and TaskError.state:
                    log.warning("Skipping further batches due to earlier critical TaskError.")
                    overall_success = False
                    break # Exit the loop

                batch_start_index = i
                batch_end_index = min(i + batch_size, total_links)
                batch_links = source_links[batch_start_index:batch_end_index]
                batch_filenames = full_filenames_list[batch_start_index:batch_end_index] if manual_filenames_provided else []

                log.info(f"--- Processing Batch {i//batch_size + 1} ({batch_start_index+1}-{batch_end_index}) / {total_links} ---")

                # 1. Clean Up Dirs
                # Use original path for consistency if zip mode isn't creating subdirs per batch
                batch_download_path = original_down_path
                Paths.down_path = batch_download_path # Set current download path
                log.info(f"Cleaning work directories before batch {i//batch_size + 1}... Target: {batch_download_path}")
                # Ensure previous batch's potential leftovers are cleaned
                if ospath.exists(batch_download_path): shutil.rmtree(batch_download_path, ignore_errors=True)
                # Clean specific temp dirs used by processing steps
                if ospath.exists(Paths.temp_zpath): shutil.rmtree(Paths.temp_zpath, ignore_errors=True)
                if ospath.exists(Paths.temp_unzip_path): shutil.rmtree(Paths.temp_unzip_path, ignore_errors=True)
                # Recreate the main download dir for this batch
                makedirs(batch_download_path, exist_ok=True)

                # 2. Download the current batch
                log.info(f"Downloading batch {i//batch_size + 1}...")
                # Reset temporary error state *before* calling download manager
                batch_task_error_state_before_dl = TaskError.state if TaskError else False
                if TaskError: TaskError.state = False; TaskError.text = ""
                await downloadManager(batch_links, is_ytdl, batch_filenames)
                # Capture download success/failure *for this batch*
                batch_download_succeeded = not (TaskError and TaskError.state)
                batch_download_error_text = TaskError.text if TaskError and TaskError.state else ""
                # Restore original error state if download succeeded but there was a prior error
                if batch_download_succeeded and batch_task_error_state_before_dl:
                    TaskError.state = True; TaskError.text = "Earlier critical error occurred."


                # 3. Handle Download Errors (Non-Breaking)
                batch_had_download_failures = False
                if not batch_download_succeeded:
                    log.warning(f"One or more downloads failed during batch {i//batch_size + 1}. Reason: {batch_download_error_text}. Continuing task.")
                    overall_success = False # Mark overall task as having failures
                    batch_had_download_failures = True # Track this specific batch had download issues

                # 4. Check if Download Directory is Empty (Can skip processing/upload)
                if not ospath.exists(batch_download_path) or not os.listdir(batch_download_path):
                    log.warning(f"Download path empty after batch {i//batch_size + 1}. Skipping processing/upload for this batch.")
                    # If download failed, reset TaskError state so the main loop continues
                    if batch_had_download_failures and TaskError:
                        TaskError.state = False
                        TaskError.text = ""
                    continue # Skip to the next iteration of the loop

                # --- 5. Process and Upload Step (Inside its own try/except) ---
                # This block executes only if download succeeded (or failed but left files) AND dir is not empty
                log.info(f"Processing/Uploading downloaded files for batch {i//batch_size + 1}...")
                log.debug(f">>> Starting processing/upload block for batch {i//batch_size + 1}.")
                batch_processing_error = False
                # --- Inner try for processing/upload ---
                try:
                     # Ensure getSize, sizeUnit, Zip/Unzip/Leech handlers are imported/available
                     TRANSFER.total_down_size = getSize(batch_download_path)
                     log.info(f"Batch download size: {sizeUnit(TRANSFER.total_down_size)}. Processing type: {BOT.Mode.type}")

                     process_path = batch_download_path
                     leech_path = None
                     cleanup_process_path = True

                     log.debug(f">>> Initial process_path: {process_path}, Mode: {BOT.Mode.type}")

                     # --- Zip/Unzip Logic ---
                     if is_zip:
                         log.debug(">>> Calling Zip_Handler...")
                         await Zip_Handler(process_path, True, True) # Assumes it removes original on success
                         if TaskError and TaskError.state: batch_processing_error = True; log.error(">>> Zip_Handler failed.")
                         else: leech_path = Paths.temp_zpath; cleanup_process_path = False; log.debug(f">>> Zip successful. leech_path set to: {leech_path}")
                     elif is_unzip:
                         log.debug(">>> Calling Unzip_Handler...")
                         await Unzip_Handler(process_path, True) # Assumes it removes original on success
                         if TaskError and TaskError.state: batch_processing_error = True; log.error(">>> Unzip_Handler failed.")
                         else: leech_path = Paths.temp_unzip_path; cleanup_process_path = False; log.debug(f">>> Unzip successful. leech_path set to: {leech_path}")
                     elif is_dualzip:
                         log.debug(">>> Calling Unzip_Handler (dual)...")
                         await Unzip_Handler(process_path, True)
                         if not TaskError or not TaskError.state:
                              log.debug(">>> Calling Zip_Handler (dual)...")
                              await Zip_Handler(Paths.temp_unzip_path, True, True)
                              if not TaskError or not TaskError.state: leech_path = Paths.temp_zpath; cleanup_process_path = False; log.debug(f">>> DualZip successful. leech_path set to: {leech_path}")
                              else: batch_processing_error = True; log.error(">>> Zip_Handler (dual) failed.")
                         else: batch_processing_error = True; log.error(">>> Unzip_Handler (dual) failed.")
                     else: # Normal mode
                          leech_path = process_path
                          cleanup_process_path = False
                          log.debug(f">>> Normal mode. leech_path set to: {leech_path}")

                     # --- Leeching Step ---
                     log.debug(f">>> Entering Leeching Step. batch_processing_error={batch_processing_error}")
                     if not batch_processing_error:
                         log.debug(f">>> Checking leech_path: {leech_path}")
                         if leech_path and ospath.exists(leech_path):
                             log.info(f"Starting Leech handler for batch from path: {leech_path}")
                             log.debug(f">>> Calling Leech function with path={leech_path}, cleanup={cleanup_process_path}")
                             await Leech(leech_path, cleanup_process_path) # Leech handles cleanup if flag True
                             log.debug(f">>> Leech function finished. Checking TaskError state...")
                             if TaskError and TaskError.state:
                                  log.error(f">>> Leech handler failed for batch {i//batch_size + 1}. Reason: {TaskError.text}")
                                  batch_processing_error = True # Mark as processing error
                             else:
                                  log.debug(">>> Leech handler seems successful (TaskError not set).")
                         elif not TaskError or not TaskError.state: # If no error previously, but path missing now
                             log.error(f">>> Processing finished but leech path missing or does not exist: {leech_path}")
                             if TaskError: TaskError.state = True; TaskError.text = f"Batch processing error ({BOT.Mode.type}) - Leech path invalid"
                             batch_processing_error = True # Mark as processing error
                         else: # TaskError already set before leech path check
                             log.warning(f">>> Leech path check skipped due to pre-existing TaskError state after processing.")
                             batch_processing_error = True # Ensure this flag is set

                # --- This except corresponds to the inner 'try' around step 5 ---
                except Exception as batch_proc_err:
                    log.error(f">>> Unhandled error during processing/upload of batch {i//batch_size + 1}: {batch_proc_err}", exc_info=True)
                    batch_processing_error = True # Mark as processing error
                    if TaskError: TaskError.state = True; TaskError.text = f"Batch processing error: {batch_proc_err}"
                # --- End Inner try/except for processing/upload ---

                log.debug(f">>> End of processing/upload block. batch_processing_error={batch_processing_error}")

                # --- Logic AFTER processing/upload try-except block, still INSIDE the loop ---
                # Reset TaskError ONLY if the error was just a download failure AND no processing error occurred
                if batch_had_download_failures and not batch_processing_error:
                    log.debug(f"Resetting TaskError state after recoverable download failure in batch {i//batch_size + 1}.")
                    if TaskError:
                       TaskError.state = False
                       TaskError.text = ""

                # Handle critical processing errors -> Break the main loop
                if batch_processing_error:
                     overall_success = False
                     # Set the main TaskError state if not already set by the specific failure
                     if TaskError and not TaskError.state: TaskError.state = True; TaskError.text = "Processing/Upload Error"
                     log.error(f"Critical processing/upload error detected in batch {i//batch_size + 1}. Reason: {TaskError.text if TaskError else 'Unknown'}. Stopping further batches.")
                     break # Stop processing further batches

                log.info(f"--- Finished Batch {i//batch_size + 1} ---")
                log.debug(">>> Reached end of loop iteration for batch.")
                # --- End of Batch Processing Logic for one iteration ---

            # --- End of Batch Loop ---

            # --- Code AFTER the Batch Loop Finishes ---
            if overall_success and (not TaskError or not TaskError.state):
                 log.info("All batches processed successfully.")
            # elif TaskError and TaskError.state: # No need for this check, handled by the final check below
                 # log.warning("Do_Leech loop finished, but TaskError state is True (likely due to critical processing error).")
            else: # Implies overall_success is False (due to recoverable download errors or critical processing error)
                 log.warning("Processing stopped or completed with errors in one or more batches.")
            # --- End Code After Loop ---

    # --- This except corresponds to the main 'try' at the start of Do_Leech ---
    except Exception as leech_err:
        log.error(f"Error in Do_Leech main execution: {leech_err}", exc_info=True)
        # Ensure TaskError state is set if an unexpected error occurred
        if TaskError and not TaskError.state:
             TaskError.state = True
             TaskError.text = f"Unexpected Leech Error: {leech_err}"
        overall_success = False # Mark failure if we hit this block
    # --- End Main Try/Except ---

    # --- Finally block for Do_Leech (Should always run) ---
    # Removed finally block here as taskScheduler handles the final cleanup/cancel/log trigger

    # --- Log sending logic at the end of Do_Leech (only if successful) ---
    # This replaces the finally block's responsibility for sending logs on success
# --- Logic to set final TaskError state based on overall_success ---
    if overall_success and (not TaskError or not TaskError.state):
        # Case 1: Everything genuinely succeeded
        log.info("Do_Leech completed successfully. TaskError is False. Calling SendLogs...")
        await SendLogs(True) # <-- RESTORED CALL TO SendLogs FOR SUCCESS
    elif not overall_success:
        # Case 2: Some error occurred (download or processing)
        log.warning("Do_Leech completed with errors (overall_success is False).")
        if TaskError and not TaskError.state:
            # If overall failed but TaskError was reset (recoverable download error), set it again!
            log.info("Setting TaskError state to True because overall_success is False.")
            TaskError.state = True
            TaskError.text = TaskError.text or "Task completed with recoverable download errors."
        elif not TaskError:
             # Create TaskError if somehow missing
             TaskError.state = True; TaskError.text = "Task completed with errors (unknown type)."

        # TaskError.state is now True. taskScheduler's finally block will call cancelTask for reporting.
        log.info("Do_Leech finished. Final TaskError state is True, relying on taskScheduler to call cancelTask.")
    else:
        # This case means overall_success=True but TaskError.state=True? Should not happen with current logic.
        log.warning("Do_Leech finished in an inconsistent state. Defaulting to error handling.")
        if TaskError and not TaskError.state: TaskError.state = True; TaskError.text="Inconsistent final state"
    # --- End of final logic block in Do_Leech ---

# --- (Include full Do_Mirror code - needs similar batching if desired) ---
async def Do_Mirror(source, is_ytdl, is_zip, is_unzip, is_dualzip):
    global BOT, TRANSFER, Paths, Messages, TaskError, log
    log.info(f"Do_Mirror started. is_ytdl(legacy)={is_ytdl}, is_zip={is_zip}, is_unzip={is_unzip}, is_dualzip={is_dualzip}")
    selected_service = BOT.Options.service_type

    # --- Remove GDrive Check --- (already done)

    # Ensure local mirror directory exists
    if not ospath.exists(Paths.mirror_dir):
        try: makedirs(Paths.mirror_dir); log.info(f"Created local mirror directory: {Paths.mirror_dir}")
        except Exception as mkdir_err:
             if TaskError: TaskError.state = True; TaskError.text = f"Cannot create local mirror dir: {mkdir_err}"
             log.error(TaskError.text); return

    original_down_path = Paths.down_path
    download_completed = False
    # --- Initialize cleanup variables ---
    cleanup_temp = False
    temp_path_to_clean = None
    dualzip_unzip_path = None
    mirror_dir_final = None
    # --- End Initializations ---

    try:
        # --- Download Phase ---
        log.info(f"Do_Mirror: Processing links via downloadManager (Service: {selected_service or 'auto'})...")
        # <<< --- GET FILENAMES LIST TO PASS --- >>>
        # Retrieve the list populated by handle_options (extract) or handle_reply (manual url)
        filenames_to_pass = BOT.Options.filenames if BOT.Options.filenames else None
        log.debug(f"Do_Mirror: Passing filenames list (Count: {len(filenames_to_pass) if filenames_to_pass else 0}) to downloadManager.")
        # <<< --- END GET FILENAMES --- >>>

        # Pass the retrieved filenames list to downloadManager
        await downloadManager(source, is_ytdl, filenames_to_pass)

        # Check TaskError state *after* downloadManager returns
        if TaskError and TaskError.state:
            log.error("Download failed before mirroring (downloadManager reported error).")
            return # Stop Do_Mirror if download failed
        else:
            download_completed = True
            log.info("Do_Mirror: Download phase completed successfully.")

        # --- Mirroring Phase ---
        if download_completed:
            process_path = original_down_path # Start with the original download path

            if not ospath.exists(process_path) or not os.listdir(process_path):
                 log.warning(f"Mirror download path empty/missing after successful download: {process_path}")
                 if not TaskError.state: TaskError.state = True; TaskError.text = "Mirror download inconsistency (Empty Dir)."
                 return

            TRANSFER.total_down_size = getSize(process_path); applyCustomName();
            log.info(f"Download complete for mirror. Size: {sizeUnit(TRANSFER.total_down_size)}.")

            # Determine final mirror destination folder name
            # (Ensure Messages.download_name is set appropriately, e.g., by downloadManager or applyCustomName)
            mirror_base_name = Messages.download_name if Messages.download_name else ospath.basename(process_path if process_path != original_down_path else source[0] if isinstance(source, list) and source else "Mirrored_Item")
            # Remove potential extensions if needed before creating folder?
            mirror_base_name, _ = ospath.splitext(mirror_base_name) # Example: remove extension
            mirror_dir_final = ospath.join(Paths.mirror_dir, mirror_base_name)
            log.info(f"Target mirror directory set to: {mirror_dir_final}")
            if not ospath.exists(mirror_dir_final): makedirs(mirror_dir_final, exist_ok=True)

            source_path_for_copy = process_path # Path containing files to be copied

            # Zip/Unzip processing before copy
            if is_zip: await Zip_Handler(process_path, True, True); source_path_for_copy = Paths.temp_zpath; cleanup_temp = True; temp_path_to_clean = Paths.temp_zpath
            elif is_unzip: await Unzip_Handler(process_path, True); source_path_for_copy = Paths.temp_unzip_path; cleanup_temp = True; temp_path_to_clean = Paths.temp_unzip_path
            elif is_dualzip: await Unzip_Handler(process_path, True); await Zip_Handler(Paths.temp_unzip_path, True, True); source_path_for_copy = Paths.temp_zpath; cleanup_temp = True; temp_path_to_clean = Paths.temp_zpath; dualzip_unzip_path = Paths.temp_unzip_path

            if TaskError.state: log.error("Zip/Unzip failed before mirroring copy."); return
            if not ospath.exists(source_path_for_copy):
                 log.error(f"Mirror source path not found after processing: {source_path_for_copy}")
                 if not TaskError.state: TaskError.state = True; TaskError.text = "Mirror source path invalid."
                 return

            # --- Mirror Copy Logic ---
            log.info(f"Mirroring content from {source_path_for_copy} to LOCAL Colab path: {mirror_dir_final}")
            try:
                 for item in os.listdir(source_path_for_copy):
                     s_item = ospath.join(source_path_for_copy, item)
                     d_item = ospath.join(mirror_dir_final, item)
                     if ospath.isdir(s_item):
                         shutil.copytree(s_item, d_item, dirs_exist_ok=True)
                     elif ospath.isfile(s_item):
                         shutil.copy2(s_item, d_item)
                 log.info(f"Successfully mirrored content to {mirror_dir_final}")
            except Exception as copy_err:
                log.error(f"Error mirroring content: {copy_err}", exc_info=True)
                if TaskError: TaskError.state = True; TaskError.text = f"Mirror copy error: {copy_err}"

        else:
             log.warning("Skipping mirror processing due to download failure.")

    except Exception as mirror_err:
        log.error(f"Error in Do_Mirror main execution: {mirror_err}", exc_info=True)
        if TaskError and not TaskError.state: TaskError.state = True; TaskError.text = f"Unexpected Mirror Error: {mirror_err}"
    finally:
        # Cleanup logic using initialized variables
        log.debug(f"Do_Mirror finally block reached. cleanup_temp={cleanup_temp}")
        if cleanup_temp and temp_path_to_clean and ospath.exists(temp_path_to_clean):
             log.info(f"Cleaning up mirror temp processing dir: {temp_path_to_clean}")
             shutil.rmtree(temp_path_to_clean, ignore_errors=True)
        if dualzip_unzip_path and ospath.exists(dualzip_unzip_path):
             log.info(f"Cleaning up mirror dualzip temp dir: {dualzip_unzip_path}")
             shutil.rmtree(dualzip_unzip_path, ignore_errors=True)
        if Paths.down_path != original_down_path: Paths.down_path = original_down_path; log.debug("Restored original Paths.down_path for Mirror")

    # Final logging/reporting based on TaskError state
    if TaskError and TaskError.state:
        log.warning(f"Do_Mirror finished with error: {TaskError.text}. Logs skipped/Cancel called.")
    else:
        log.info("Do_Mirror completed without error state. Sending logs...")
        await SendLogs(False) # False indicates Mirror mode
        log.info("Do_Mirror finished successfully.")
