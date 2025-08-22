# /content/Telegram-Leecher/colab_leecher/__main__.py

import logging
import os
import asyncio
import re # Import regex module
import aiohttp # Import aiohttp
from pyrogram import filters, Client
from datetime import datetime
from asyncio import sleep, get_event_loop
from colab_leecher import colab_bot, OWNER, DUMP_ID # Absolute import
from . import aliases  # registers /mirror,/leech,/ytdl,/count,/del,/stats
from .utility.handler import cancelTask
from .utility.variables import BOT, MSG, BotTimes, Paths, TRANSFER, TaskError
from .utility.task_manager import taskScheduler, task_starter
from .utility.helper import (
    isLink, setThumbnail, message_deleter, send_settings,
    clean_filename, extract_filename_from_url, apply_dot_style, sizeUnit # Import sizeUnit if needed
)
# Import NZB search helper
from . import nzb_search
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message
# Example import line in __main__.py
from .utility.helper import (
    isLink, setThumbnail, message_deleter, send_settings,
    clean_filename, extract_filename_from_url, apply_dot_style, sizeUnit,
    keyboard, fetch_links_from_url, fetch_filenames_from_url
)

# Import configuration and settings managers
from .utility.config_manager import Config  # Provides access to environment variables
from .utility.bot_settings import bot_settings  # Default bot settings container
from .utility.users_settings import user_settings_store  # In memory user settings store

# Import the web server starter
from .web import run_server

import threading  # Used to launch the web server in a background thread


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

log.info(f"--> MERGED V1: colab_bot instance used in __main__.py: ID = {id(colab_bot)}")

src_request_msg = None
reply_prompt_message_id = None

# --- Helper function to ask for leech type (normal/zip/unzip) ---
async def ask_leech_type(client, chat_id, mode_name, reply_to_message_id=None):
    log.info(f"Asking leech type (Mode: {mode_name}) for chat {chat_id}")
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Regular", callback_data="leechtype_normal")],
         [InlineKeyboardButton("Compress", callback_data="leechtype_zip"), InlineKeyboardButton("Extract", callback_data="leechtype_unzip")],
         [InlineKeyboardButton("UnDoubleZip", callback_data="leechtype_undzip")],
         [InlineKeyboardButton("Cancel Task", callback_data="cancel")]] # Add cancel here
    )
    text = f"<b> Select Processing Type You Want » </b>\n\nRegular:<i> Normal file upload</i>\nCompress:<i> Zip file upload</i>\nExtract:<i> extract before upload</i>\nUnDoubleZip:<i> Unzip then compress</i>"
    try:
        # Send as new message instead of editing/replying maybe?
        await client.send_message(chat_id, text, reply_markup=keyboard)
        # if reply_to_message_id: await client.send_message(chat_id, text, reply_markup=keyboard, reply_to_message_id=reply_to_message_id)
        # else: await client.send_message(chat_id, text, reply_markup=keyboard)
    except Exception as e: log.error(f"Failed send leech type prompt: {e}", exc_info=True)

# --- Helper function to ask for filename option (Debrid/bitso) ---
async def ask_filename_option(client, chat_id, service_name):
    log.info(f"Asking filename option for {service_name}")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Yes, Extract from URL", callback_data=f'fn_{service_name.lower()}_extract')],
        [InlineKeyboardButton("No, Provide Manually", callback_data=f'fn_{service_name.lower()}_manual')],
        [InlineKeyboardButton("Cancel Task", callback_data='cancel')]
    ])
    await client.send_message(chat_id, f"🏷️ For {service_name}, extract filenames automatically from URLs?", reply_markup=keyboard)

# --- Helper function to ask for manual filenames ---
async def ask_manual_filenames(client, chat_id, service_name, count):
    global reply_prompt_message_id
    log.info(f"Asking for {count} manual filenames for {service_name}")
    prompt_msg = await client.send_message(chat_id, f"📝 Okay, **reply to this message** with the {count} filename(s) for {service_name}, one per line.")
    reply_prompt_message_id = prompt_msg.id # Store prompt ID

# --- Existing Command Handlers ---
@colab_bot.on_message(filters.command("start") & filters.private)
async def start(client, message):
    log.info(f"Received /start from {message.from_user.id}")
    await message.delete(); text = "**Yo! 👋🏼 It's Colab Leecher** ..."; keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Repo", url="https://github.com/thesadeq/Telegram-Leecher")]]); await message.reply_text(text, reply_markup=keyboard)

@colab_bot.on_message(filters.command("tupload") & filters.private)
async def telegram_upload(client, message):
    global BOT, src_request_msg
    log.info(f"Received /tupload from {message.from_user.id}")
    # Reset relevant options and prompt user for links.  Previous versions of the
    # bot attempted to handle Spotify downloads here, but the variable
    # ``spotify_url`` was never defined, leading to a ``NameError``.  The
    # refactored version treats ``/tupload`` as a generic leech (upload) command.
    BOT.Mode.mode = "leech"
    BOT.Mode.ytdl = False
    BOT.Options.service_type = None

    # Ask the user for the links to process.  The task_starter helper will
    # register the pending upload and return a message object that can be
    # updated later with status information.
    text = (
        "<b>⚡ Leech Task » Send Me THE LINK(s) 🔗</b>\n\n"
        "You can send direct URLs, magnet links, telegram file links, Mega links,\n"
        "Google Drive links, Debrid links, NZB, or bitso URLs.  Optionally you can\n"
        "specify a custom file name and zip/unzip passwords on separate lines.\n\n"
        "<code>https://link1.xyz\n[name.ext]\n{zip_pw}\n(unzip_pw)</code>"
    )
    src_request_msg = await task_starter(message, text)
    log.debug("/tupload: task_starter called, waiting for user links")
# --- END ADDED ---


@colab_bot.on_message(filters.command("gdupload") & filters.private)
async def drive_upload(client, message):
    global BOT, src_request_msg
    log.info(f"Received /gdupload from {message.from_user.id}")
    BOT.Mode.mode = "mirror"; BOT.Mode.ytdl = False; BOT.Options.service_type = None # Reset service type
    text = "<b>♻️ Mirror Task » Send Me THEM LINK(s) 🔗</b>\n\n(Direct, Magnet, TG, Mega, GDrive, Debrid, NZB, bitso)\n\n<code>https//link1.xyz\n[name.ext]\n{zip_pw}\n(unzip_pw)</code>"
    src_request_msg = await task_starter(message, text)
    log.debug(f"/gdupload: task_starter called, src_request_msg set")

@colab_bot.on_message(filters.command("drupload") & filters.private)
async def directory_upload(client, message):
    global BOT, src_request_msg
    log.info(f"Received /drupload from {message.from_user.id}")
    BOT.Mode.mode = "dir-leech"; BOT.Mode.ytdl = False; BOT.Options.service_type = "local" # Set service type
    text = "<b>⚡ Dir Leech » Send Me FOLDER PATH 🔗</b> ...<code>/path/to/folder</code>"
    src_request_msg = await task_starter(message, text)
    log.debug(f"/drupload: task_starter called, src_request_msg set")

@colab_bot.on_message(filters.command("ytupload") & filters.private)
async def yt_upload(client, message):
    global BOT, src_request_msg
    log.info(f"Received /ytupload from {message.from_user.id}")
    BOT.Mode.mode = "leech"; BOT.Mode.ytdl = True; BOT.Options.service_type = "ytdl" # Set service type
    text = "<b>🏮 YTDL Leech » Send Me LINK(s) 🔗</b> ...<code>https//link1.mp4</code>"
    src_request_msg = await task_starter(message, text)
    log.debug(f"/ytupload: task_starter called, src_request_msg set")

@colab_bot.on_message(filters.command("nzbsearch") & filters.private)
async def nzb_search_command(client: Client, message: Message):
    """Handle the /nzbsearch command.

    Users can search for NZB files via NZBHydra by sending a query
    string after the command.  The bot will respond with a short list
    of search results containing the title and corresponding NZB link.
    """
    log.info(f"Received /nzbsearch from {message.from_user.id}")
    # Extract the search query by removing the command part
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply_text("Please provide a search query after /nzbsearch.\nExample: /nzbsearch ubuntu iso")
        return
    query = parts[1].strip()
    try:
        results = await nzb_search.search_nzb(query)
    except Exception as e:
        log.error(f"NZB search failed: {e}")
        await message.reply_text(f"NZB search failed: {e}")
        return
    # Build response text
    if not results:
        await message.reply_text("No NZB results found for your query.")
        return
    reply_lines = ["<b>NZB Search Results:</b>"]
    for idx, item in enumerate(results[:10], start=1):
        title = item.get("title", "No Title")
        link = item.get("link", "")
        size = item.get("size", "")
        reply_lines.append(f"{idx}. <a href=\"{link}\">{title}</a> ({size})")
    reply_text = "\n".join(reply_lines)
    await message.reply_text(reply_text, disable_web_page_preview=False)

# --- REMOVED /nzbclouddownload, /Debriddownload, /bitsodownload handlers ---

@colab_bot.on_message(filters.command("settings") & filters.private)
async def settings(client, message):
    log.info(f"Received /settings from {message.from_user.id}")
    if message.chat.id == OWNER: await message.delete(); await send_settings(client, message, message.id, True)
    else: log.warning(f"Unauthorized /settings from {message.from_user.id}")

# --- Reply Handler: Simplified for filenames only ---
@colab_bot.on_message(filters.reply & filters.private)
async def handle_reply(client: Client, message: Message):
    global BOT, reply_prompt_message_id, src_request_msg # Declare globals used
    log = logging.getLogger(__name__) # Ensure logger access
    log.debug(f"Received reply (ID: {message.id}) from user {message.from_user.id}")

    # Check if the reply is for the expected prompt message ID
    if not reply_prompt_message_id or not message.reply_to_message_id or message.reply_to_message_id != reply_prompt_message_id:
        log.debug(f"Reply (ID: {message.id}) is not for the expected prompt message ID ({reply_prompt_message_id}). Ignoring.")
        return

    # Try to get the original prompt message (optional, for deletion/context)
    original_prompt_msg = None
    try:
        if message.reply_to_message_id:
            original_prompt_msg = await client.get_messages(message.chat.id, message.reply_to_message_id)
    except Exception as get_err:
        log.warning(f"Could not get original prompt message {message.reply_to_message_id}: {get_err}")

    state_handled = False
    mode_name = "" # Initialize mode_name
    current_service = BOT.Options.service_type # Get selected service

    try:
        # --- Handle Filename Replies ---
        # Check if we are expecting filenames for any supported service
        expecting_filenames_now = (current_service == "nzbcloud" and BOT.State.expecting_nzb_filenames) or \
                                  (current_service == "Debrid" and BOT.State.expecting_Debrid_filenames) or \
                                  (current_service == "bitso" and BOT.State.expecting_bitso_filenames)

        if expecting_filenames_now:
            log.info(f"Processing filename reply for service: {current_service}...")
            user_input = message.text.strip() if message.text else "" # Ensure text exists
            expected_count = len(BOT.SOURCE) # Determine expected count *once*

            # <<< --- START LOGGING (Expected Count) --- >>>
            log.debug(f"HANDLE_REPLY: Expecting {expected_count} filenames based on BOT.SOURCE.")
            log.debug(f"HANDLE_REPLY: BOT.SOURCE content (first 5): {BOT.SOURCE[:5] if BOT.SOURCE else '[]'}")
            # <<< --- END LOGGING --- >>>

            filenames_to_use = []
            input_processed = False

            # Check if the input looks like a supported URL for filenames
            is_potential_url = False
            if user_input.lower().startswith(('http://', 'https://')):
                # Basic check, fetch_filenames_from_url will do a more specific check
                if ("pastebin.com" in user_input or "gist.githubusercontent.com" in user_input or
                    "rentry.co" in user_input or user_input.lower().endswith(".txt")):
                      is_potential_url = True

            # --- Process URL Input ---
            if is_potential_url:
                log.info(f"Detected potential filename URL: {user_input}")
                # fetch_filenames_from_url now returns raw, stripped lines
                raw_lines_list = await fetch_filenames_from_url(user_input)

                # Get counts for comparison
                fetched_count = len(raw_lines_list) if raw_lines_list is not None else -1

                # <<< --- START LOGGING (URL) --- >>>
                log.debug(f"HANDLE_REPLY (URL): Raw lines fetched from URL: {raw_lines_list}")
                log.debug(f"HANDLE_REPLY (URL): Comparing Counts -> Fetched: {fetched_count}, Expected: {expected_count}")
                # <<< --- END LOGGING --- >>>

                if raw_lines_list is None:
                    # Fetching failed
                    await message.reply_text(f"❌ Failed to fetch filenames from the provided URL or it's unsupported. Please provide a direct reply or a valid raw link (Gist/Pastebin/Rentry/.txt).", quote=True)
                    log.warning(f"fetch_filenames_from_url returned None for: {user_input}")
                    # Keep expecting reply (don't set state_handled=True)

                elif fetched_count != expected_count:
                    # Count mismatch based on raw lines
                    log.warning("Raw filename line count mismatch.")
                    await message.reply_text(f"❌ Found {fetched_count} non-empty lines in the URL, but expected {expected_count} filenames (matching the number of links). Please check the file content and reply again.", quote=True)
                    # Keep expecting reply (don't set state_handled=True)

                else:
                    # Counts match! Now clean and style the raw lines
                    log.info(f"Raw line count matches expected count ({expected_count}). Cleaning/styling filenames...")
                    filenames_to_use = []
                    all_valid_after_cleaning = True
                    for i, raw_line in enumerate(raw_lines_list):
                        cleaned = clean_filename(raw_line)
                        if cleaned:
                            styled = apply_dot_style(cleaned)
                            filenames_to_use.append(styled)
                        else:
                            log.warning(f"Filename at line {i+1} ('{raw_line[:50]}...') became invalid after cleaning. Aborting.")
                            await message.reply_text(f"❌ Filename at line {i+1} ('{raw_line[:50]}...') is invalid after cleaning. Please check your list and reply again.", quote=True)
                            all_valid_after_cleaning = False
                            break # Stop processing if any filename is invalid

                    if all_valid_after_cleaning:
                        # Success! All filenames cleaned successfully
                        BOT.Options.filenames = filenames_to_use # Store the final cleaned list
                        input_processed = True
                        log.info(f"Successfully cleaned and stored {len(filenames_to_use)} filenames from URL.")
                    # Else (all_valid_after_cleaning is False): Error message already sent, loop broken.

            # --- Process Direct Text Input ---
            else:
                log.info("Processing input as direct filename list.")
                filenames_raw = [fn.strip() for fn in user_input.splitlines() if fn.strip()]
                fetched_count = len(filenames_raw) # Get count of non-empty raw lines

                # <<< --- START LOGGING (Direct) --- >>>
                log.debug(f"HANDLE_REPLY (Direct): Raw lines from input: {filenames_raw}")
                log.debug(f"HANDLE_REPLY (Direct): Comparing Counts -> Fetched: {fetched_count}, Expected: {expected_count}")
                # <<< --- END LOGGING --- >>>

                if fetched_count != expected_count:
                     # Count mismatch based on direct input lines
                     log.warning("Filename count mismatch (direct input).")
                     await message.reply_text(f"❌ Expected {expected_count} filenames, but got {fetched_count}. Reply again with the correct number of filenames.", quote=True)
                     # Keep expecting reply (don't set state_handled=True)
                else:
                     # Counts match! Now clean and style the raw lines
                     log.info(f"Direct input count matches expected count ({expected_count}). Cleaning/styling filenames...")
                     filenames_to_use = []
                     all_valid_after_cleaning = True
                     for i, raw_line in enumerate(filenames_raw):
                         cleaned = clean_filename(raw_line)
                         if cleaned:
                             styled = apply_dot_style(cleaned)
                             filenames_to_use.append(styled)
                         else:
                             log.warning(f"Direct filename at line {i+1} ('{raw_line[:50]}...') became invalid after cleaning. Aborting.")
                             await message.reply_text(f"❌ Filename at line {i+1} ('{raw_line[:50]}...') is invalid after cleaning. Please check your input and reply again.", quote=True)
                             all_valid_after_cleaning = False
                             break # Stop processing if any filename is invalid

                     if all_valid_after_cleaning:
                          # Success! All filenames cleaned successfully
                          BOT.Options.filenames = filenames_to_use # Store the final cleaned list
                          input_processed = True
                          log.info(f"Successfully cleaned and stored {len(filenames_to_use)} filenames from direct input.")

            # --- Post-processing (only if input_processed is True) ---
            if input_processed:
                state_handled = True
                # Reset specific state and get mode name
                if current_service == "nzbcloud": BOT.State.expecting_nzb_filenames = False; mode_name = "NZBCloud"
                elif current_service == "Debrid": BOT.State.expecting_Debrid_filenames = False; mode_name = "DebridLeech"
                elif current_service == "bitso": BOT.State.expecting_bitso_filenames = False; mode_name = "bitso"
                log.info(f"Received valid filenames for {mode_name} ({'URL' if is_potential_url else 'Direct'}).")

                # Try deleting the original prompt message if obtained
                if original_prompt_msg:
                    try: await original_prompt_msg.delete()
                    except Exception as del_err: log.warning(f"Could not delete original prompt: {del_err}")

                # Filenames received, now ask for leech type (normal/zip/unzip)
                # Make sure ask_leech_type is correctly imported/defined
                await ask_leech_type(client, message.chat.id, BOT.Mode.mode)


        # --- Handle Prefix/Suffix replies ---
        elif BOT.State.prefix:
            log.info("Processing prefix reply...")
            BOT.Setting.prefix = message.text.strip() if message.text else "" # Strip whitespace
            BOT.State.prefix = False
            state_handled = True
            # Try sending updated settings if original prompt message exists
            if original_prompt_msg:
                try:
                    # Make sure send_settings is correctly imported/defined
                    await send_settings(client, original_prompt_msg, original_prompt_msg.id, False)
                except Exception as send_err:
                    log.error(f"Failed to send settings after prefix: {send_err}")
                    await message.reply_text("Prefix set!") # Fallback confirmation
            else:
                await message.reply_text("Prefix set!") # Fallback confirmation


        elif BOT.State.suffix:
            log.info("Processing suffix reply...")
            BOT.Setting.suffix = message.text.strip() if message.text else "" # Strip whitespace
            BOT.State.suffix = False
            state_handled = True
            # Try sending updated settings if original prompt message exists
            if original_prompt_msg:
                try:
                    # Make sure send_settings is correctly imported/defined
                    await send_settings(client, original_prompt_msg, original_prompt_msg.id, False)
                except Exception as send_err:
                    log.error(f"Failed to send settings after suffix: {send_err}")
                    await message.reply_text("Suffix set!") # Fallback confirmation
            else:
                await message.reply_text("Suffix set!") # Fallback confirmation

        else:
            # This case should ideally not be reached if the prompt ID check works
            log.warning(f"Received reply (for msg {reply_prompt_message_id}) but no matching state active. Ignoring.")

    except Exception as e:
        log.error(f"Error processing reply: {e}", exc_info=True)
        # Inform user about the error
        try: await message.reply_text(f"⚠️ Error processing your reply: {e}", quote=True)
        except Exception: pass # Ignore if sending error fails

    finally:
        # --- Final cleanup inside handle_reply ---
        if state_handled:
            log.debug(f"State handled for reply {message.id}. Resetting prompt ID.")
            reply_prompt_message_id = None # Reset prompt ID as it's been handled
            try:
                # Check if message exists before deleting
                if message: await message.delete() # Delete user's reply
            except Exception as del_err:
                 log.warning(f"Could not delete user reply message {message.id if message else 'N/A'}: {del_err}")
        else:
            # Only log if we were actually expecting a reply (prompt ID was set)
            if reply_prompt_message_id == message.reply_to_message_id:
                 log.debug(f"State not handled for reply {message.id}. Prompt ID {reply_prompt_message_id} remains active.")
            # No need to log if the reply wasn't for our prompt anyway


async def fetch_and_parse_links(url: str) -> list[str] | None:
    """
    Fetches content from supported raw text URLs (Pastebin, Gist, Rentry)
    and parses valid links (http/https/magnet).
    Returns a list of links or None on failure or if URL is not supported.
    """
    log = logging.getLogger(__name__) # Get logger instance
    # Ensure necessary modules are imported where this function is defined
    import re
    import aiohttp

    raw_url = None
    cleaned_url = url.strip() # Clean input URL

    # --- Identify supported services and get raw URL ---
    if "pastebin.com" in cleaned_url:
        match = re.match(r"https?://pastebin\.com/raw/(\w+)", cleaned_url)
        if match:
            raw_url = cleaned_url
        else:
            match = re.match(r"https?://pastebin\.com/(\w+)", cleaned_url)
            if match:
                raw_url = f"https://pastebin.com/raw/{match.group(1)}"
    elif "gist.githubusercontent.com" in cleaned_url and "/raw" in cleaned_url:
         # Directly handle raw gist URLs
         raw_url = cleaned_url
    elif "rentry.co" in cleaned_url:
        match = re.match(r"https?://rentry\.co/(\w+)", cleaned_url.split('/raw')[0]) # Get base code
        if match:
            raw_url = f"https://rentry.co/{match.group(1)}/raw" # Ensure /raw

    # Add simple check for direct .txt links
    elif cleaned_url.lower().startswith(('http://', 'https://')) and cleaned_url.lower().endswith(".txt"):
         raw_url = cleaned_url

    if not raw_url:
        # log.debug(f"URL not recognized as a supported raw paste/gist/rentry/txt link: {cleaned_url}")
        return None # Indicate not a supported URL type for fetching

    log.info(f"Attempting to fetch links from detected raw URL: {raw_url}")
    try:
        async with aiohttp.ClientSession() as session:
            # Add headers to potentially mimic a browser
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            async with session.get(raw_url, timeout=20, headers=headers) as response: # Increased timeout
                log.debug(f"Fetching URL status: {response.status}")
                response.raise_for_status() # Raise exception for bad status codes
                text_content = await response.text()

                if not text_content:
                    log.warning(f"Fetched empty content from {raw_url}")
                    return []

                # Parse links - one per line, basic validation
                links = []
                for line in text_content.splitlines():
                    line = line.strip()
                    # Basic check for http/https/magnet/ftp links - refine regex if needed
                    if re.match(r"^(https?://|magnet:\?|ftps?://)", line):
                        links.append(line)
                    elif line: # Log non-empty lines that don't look like links
                         log.debug(f"Ignoring non-link line: {line[:100]}...")


                log.info(f"Parsed {len(links)} links from {raw_url}")
                return links

    except aiohttp.ClientError as e:
        log.error(f"HTTP Client Error fetching links from {raw_url}: {e}")
        # Optionally: Inform user fetch failed
        # await client.send_message(chat_id=OWNER, text=f"⚠️ Failed to fetch links from {url}: {e}")
        return None # Return None on fetch errors
    except Exception as e:
        log.error(f"Unexpected error fetching/parsing links from {raw_url}: {e}", exc_info=True)
        # Optionally: Inform user fetch failed
        # await client.send_message(chat_id=OWNER, text=f"⚠️ Failed to parse links from {url}: {e}")
        return None # Return None on other errors

# --- End of function definition ---
# URL Handler: Modified to handle external link lists
# URL Handler: Modified to handle external link lists AND failed parsing
# Add this function definition inside __main__.py
async def ask_service_type(client, message):
     """Sends a new message asking for the download service type."""
     # Ensure OWNER is imported or accessible
     from colab_leecher import OWNER
     log = logging.getLogger(__name__)
     log.info("Asking user to select download service...")
     # Define keyboard
     keyboard_markup = InlineKeyboardMarkup([
          [InlineKeyboardButton("Aria", callback_data='service_direct'), InlineKeyboardButton("Debrid", callback_data='service_Debrid')],
          [InlineKeyboardButton("NZBCloud", callback_data='service_nzbcloud'), InlineKeyboardButton("Bitso", callback_data='service_bitso')],
          [InlineKeyboardButton("Cancel Task", callback_data='cancel')]
     ])
     try:
         # --- FIX: Send a new message instead of editing ---
         # Reply to the user's message containing the links for context
         if message and hasattr(message, 'reply_text'):
              await message.reply_text(
                  "👇 **Select Download Service** for these links:",
                  reply_markup=keyboard_markup,
                  quote=True # Quote the user's link message
              )
         else:
              # Fallback if message context is somehow lost (shouldn't happen often)
              log.warning("ask_service_type: Message context lost, sending to OWNER.")
              await client.send_message(
                  OWNER,
                  "👇 **Select Download Service** for the links provided:",
                  reply_markup=keyboard_markup
              )
         # --- END FIX ---
     except Exception as e:
          log.error(f"Failed to ask service type: {e}", exc_info=True)
          # Try sending error message to owner as fallback
          try: await client.send_message(OWNER, f"⚠️ Error asking service type: {e}")
          except Exception: pass
# --- End ask_service_type function ---

# --- Replace the entire handle_url function ---
@colab_bot.on_message(filters.create(isLink) & ~filters.photo & filters.private)
async def handle_url(client: Client, message: Message):
    global BOT, src_request_msg, reply_prompt_message_id
    user_id = message.from_user.id

    # --- Initial State Checks ---
    # Ignore if expecting filenames (let handle_reply handle it)
    if BOT.State.expecting_nzb_filenames or \
       BOT.State.expecting_Debrid_filenames or \
       BOT.State.expecting_bitso_filenames:
        log.debug("handle_url: Ignoring link/path message because bot is expecting filenames.")
        return

    # Allow only owner input if task is started but not yet running
    if BOT.State.started and not BOT.State.task_going and user_id != OWNER:
        await message.reply_text("Bot is waiting for owner input.")
        return

    # Ignore if another task is actively running
    if BOT.State.task_going:
        log.warning("Task going, ignoring link/path in handle_url.")
        await message.reply_text("<i>🚨 Already working!</i>")
        return

    # Ignore if no task command was initiated
    if not BOT.State.started:
        log.warning("Task not started by command, ignoring link/path in handle_url.")
        await message.reply_text("<i>Start task with /tupload, /gdupload, or /drupload first.</i>")
        return
    # --- End Initial State Checks ---


    log.info(f"Handling URL/Path message from user {user_id}. Current Mode: {BOT.Mode.mode}")
    # Reset options initially
    BOT.Options.custom_name = ""; BOT.Options.zip_pswd = ""; BOT.Options.unzip_pswd = ""; BOT.Options.filenames = []; BOT.Options.service_type = None # Reset service type here

    # Delete the initial prompt message ("Send Me THEM LINK(s)...")
    if src_request_msg:
        try: await src_request_msg.delete(); src_request_msg = None
        except Exception as del_err: log.warning(f"Could not delete source request prompt: {del_err}"); src_request_msg = None

    try:
        input_text = message.text.strip() if message.text else ""
        if not input_text:
             await message.reply_text("❌ Input cannot be empty."); BOT.State.started = False; return

        # --- === Handle Directory Leech Path === ---
        if BOT.Mode.mode == "dir-leech":
            log.info(f"Processing input as directory path for dir-leech: '{input_text}'")
            # Check if path exists
            if not os.path.exists(input_text):
                 log.error(f"Dir-leech path does not exist: {input_text}")
                 await message.reply_text(f"❌ Path not found or invalid: `{input_text}`")
                 BOT.State.started = False # Reset state as input was invalid
                 return

            # Path is valid, store it
            BOT.SOURCE = [input_text]
            BOT.Options.service_type = "local" # Confirm service type
            log.info(f"Stored valid path for dir-leech. Source: {BOT.SOURCE}")

            # Dir-leech doesn't need service selection, proceed to leech type selection
            await ask_leech_type(client, message.chat.id, BOT.Mode.mode) # Ask normal/zip/unzip
            # The task will be scheduled after leech type is selected via callback

        # --- === Handle Normal Link Processing (Leech/Mirror Modes) === ---
        else:
            log.info("Processing input as URL(s) for leech/mirror mode...")
            urls = []
            extracted_args = {"custom_name": "", "zip_pswd": "", "unzip_pswd": ""}

            # Try fetching external links first
            parsed_links = None
            try: parsed_links = await fetch_links_from_url(input_text) # Ensure fetch_links_from_url is imported
            except Exception as fetch_err: log.error(f"Error during fetch_links_from_url call: {fetch_err}", exc_info=True)

            if parsed_links is not None: # Recognized as potential external list URL
                if not parsed_links:
                     log.warning(f"External URL '{input_text}' contained no valid links.")
                     await message.reply_text(f"❌ Found 0 valid links in the provided URL: {input_text}")
                     BOT.State.started = False; return
                log.info(f"Using {len(parsed_links)} links fetched from external URL: {input_text}")
                urls = parsed_links
            else:
                # Fallback: Process message directly for links and args
                log.info("Input not recognized as external list URL, processing directly.")
                # ... (existing logic for parsing links/args from message text) ...
                temp_source = [line.strip() for line in input_text.splitlines() if line.strip()]
                args_to_remove = 0
                for line in reversed(temp_source):
                     is_arg = False
                     if line.startswith("[") and line.endswith("]"): extracted_args["custom_name"] = line[1:-1]; is_arg = True
                     elif line.startswith("{") and line.endswith("}"): extracted_args["zip_pswd"] = line[1:-1]; is_arg = True
                     elif line.startswith("(") and line.endswith(")"): extracted_args["unzip_pswd"] = line[1:-1]; is_arg = True
                     if is_arg: args_to_remove += 1
                     else: break
                urls = temp_source[:-args_to_remove] if args_to_remove > 0 else temp_source

            # Set options from extracted args (only applies to direct message input)
            BOT.Options.custom_name = extracted_args["custom_name"]
            BOT.Options.zip_pswd = extracted_args["zip_pswd"]
            BOT.Options.unzip_pswd = extracted_args["unzip_pswd"]
            BOT.Options.filenames = [] # Reset filenames

            if not urls:
                log.warning("No valid URLs found after processing."); await message.reply_text("❌ No valid URLs found in the message."); BOT.State.started = False; return

            # Basic validation check (similar to previous version)
            standard_download_pattern = re.compile(r"^(https?://|magnet:\?|ftps?://)")
            paste_site_pattern = re.compile(r"pastebin\.com|gist\.github|rentry\.co|pastes\.io|pastie\.org")
            if parsed_links is None and len(urls) == 1 and urls[0] == input_text:
                if not standard_download_pattern.match(urls[0]) or paste_site_pattern.search(urls[0]):
                     log.error(f"Input '{input_text}' was not parsed and is not a direct download link.")
                     await message.reply_text(f"❌ Input is not a direct download link or a supported raw list URL: {input_text}")
                     BOT.State.started = False; return

            BOT.SOURCE = urls # Store the final list of links
            log.info(f"Received {len(BOT.SOURCE)} URLs for mode {BOT.Mode.mode} in handle_url.")

            # Ask for Service Type (only needed for leech/mirror link modes)
            await ask_service_type(client, message) # Ensure ask_service_type is imported

    except Exception as e:
        log.error(f"Error handling URL/Path message: {e}", exc_info=True)
        await message.reply_text(f"⚠️ Error processing input: {e}")
        BOT.State.started = False # Reset state on error
# --- End handle_url ---

@colab_bot.on_callback_query()
async def handle_options(client: Client, callback_query: CallbackQuery):
    global BOT, MSG, TaskError, TRANSFER, OWNER, DUMP_ID, src_request_msg, reply_prompt_message_id
    user_id = callback_query.from_user.id
    message = callback_query.message
    query_data = callback_query.data
    # Use message context safely
    msg_id = message.id if message else None
    chat_id = message.chat.id if message and hasattr(message, 'chat') else OWNER # Default to OWNER if chat missing

    # Authorization Checks (ensure correct indentation)
    if BOT.State.started and not BOT.State.task_going and user_id != OWNER:
        await callback_query.answer("Please wait for the owner...", show_alert=True)
        return
    if BOT.State.task_going and query_data == "cancel" and user_id != OWNER:
        await callback_query.answer("Only owner can cancel.", show_alert=True)
        return
    # Assuming settings callbacks start with "setting_" or similar prefixes handled later
    # Example check (adjust if needed):
    if query_data.startswith(("setting_", "video", "caption", "thumb", "set-suffix", "set-prefix", "close", "back")) and user_id != OWNER:
         await callback_query.answer("Owner only settings.", show_alert=True)
         return
    if not message:
        await callback_query.answer("Original message lost?", show_alert=True)
        log.error("Callback query failed: Message context lost.")
        return

    log.info(f"Handling callback query: {query_data} from user {user_id}")

    try: # Main try block starts here
        # --- Service Selection ---
        if query_data.startswith("service_"):
            await callback_query.answer() # Acknowledge first
            service = query_data.split("_", 1)[1]
            log.info(f"User selected service: {service}")
            BOT.Options.service_type = service

            # Delete the service selection message AFTER processing choice
            try:
                await message.delete()
            except Exception as e:
                log.warning(f"Could not delete service selection message: {e}")

            
            filenames_needed_choice = service in ["Debrid", "bitso", "nzbcloud"] 

            if filenames_needed_choice:
                log.info(f"Asking filename option for {service.capitalize()}")
                await ask_filename_option(client, chat_id, service.capitalize()) # Pass chat_id
            else:
                # No filename choice needed for this service
                log.info(f"Service '{service}' selected. Proceeding to ask leech type.")
                await ask_leech_type(client, chat_id, BOT.Mode.mode)

        # --- Filename Options ---
        # <<< THIS BLOCK'S INDENTATION MUST MATCH THE 'if' ABOVE >>>
        elif query_data.startswith("fn_"):
            await callback_query.answer()
            # Make sure service_type and fn_choice parsing is correct
            parts = query_data.split("_")
            if len(parts) < 3:
                 log.error(f"Invalid fn_ query data format: {query_data}")
                 await callback_query.answer("Internal error parsing choice.", show_alert=True)
                 return

            service_type = parts[1] # e.g., 'Debrid' or 'bitso'
            fn_choice = parts[2]    # e.g., 'extract' or 'manual'

            if fn_choice == "extract":
                log.info(f"User chose extract filenames for {service_type}.")
                extracted_filenames = []
                if not BOT.SOURCE:
                    await message.edit_text("❌ Error: No links found.")
                    BOT.State.started = False
                    return

                log.info(f"Extracting filenames for {len(BOT.SOURCE)} links...")
                all_extracted = True # Flag to track success
                for i, link in enumerate(BOT.SOURCE):
                    extracted_name = await extract_filename_from_url(link) # Use await
                    if extracted_name:
                        cleaned = apply_dot_style(clean_filename(extracted_name))
                        if cleaned: # Ensure cleaning didn't result in None
                             extracted_filenames.append(cleaned)
                             log.debug(f"Extracted and cleaned name for link {i+1}: {cleaned}")
                        else:
                             log.warning(f"Filename invalid after cleaning for link {i+1}: {link}. Aborting.")
                             await message.edit_text(f"❌ Error: Invalid filename after cleaning link #{i+1}. Task Cancelled.")
                             all_extracted = False; break # Stop loop
                    else:
                        log.warning(f"Failed to extract filename for link {i+1}: {link}. Aborting.")
                        await message.edit_text(f"❌ Error extracting filename for link #{i+1}. Task Cancelled.")
                        all_extracted = False; break # Stop loop

                if all_extracted:
                    BOT.Options.filenames = extracted_filenames
                    log.info(f"Extraction success: {len(extracted_filenames)} filenames.")
                    # Check if message still exists before deleting
                    if message: await message.delete() # Delete filename option message
                    await ask_leech_type(client, chat_id, BOT.Mode.mode) # Ask next step
                else:
                    # Extraction failed, reset relevant states
                    BOT.State.started = False; TaskError.reset(); TRANSFER.reset(); BOT.SOURCE=[]; BOT.Options.filenames=[] # Reset state

            elif fn_choice == "manual":
                log.info(f"User chose manual filenames for {service_type}.")
                expected_count = len(BOT.SOURCE)
                # This is where the prompt message is defined and sent:
                prompt_text = (f"📝 Okay, **reply to this message** with the {expected_count} filename(s) for {service_type.capitalize()}, one per line.\n\n"
                               f"**OR provide a link** (Gist/Pastebin/Rentry raw URL, or direct `.txt` link) containing the filenames.")
                try:
                    # Send the prompt
                    prompt_msg = await client.send_message(chat_id, prompt_text)
                    reply_prompt_message_id = prompt_msg.id # Store prompt ID
                    # Check if message still exists before deleting
                    if message: await message.delete() # Delete the button message
                    # Set state to expect reply
                    if service_type == 'Debrid': BOT.State.expecting_Debrid_filenames = True
                    elif service_type == 'bitso': BOT.State.expecting_bitso_filenames = True
                    elif service_type == 'nzbcloud': BOT.State.expecting_nzb_filenames = True    
                    # Add nzbcloud if needed: elif service_type == 'nzbcloud': BOT.State.expecting_nzb_filenames = True
                except Exception as e:
                    log.error(f"Failed to send manual filename prompt: {e}")
                    if message: await client.send_message(chat_id, f"❌ Error asking for filenames: {e}") # Use message if possible

            else:
                log.warning(f"Unknown filename choice: {fn_choice}")
                if message: await message.edit_text("⚠️ Unknown filename option.")

        # --- Leech Type Selection ---
        # <<< THIS BLOCK'S INDENTATION MUST MATCH THE 'if' AND 'elif' ABOVE >>>
        elif query_data.startswith("leechtype_"):
            await callback_query.answer()
            leech_type = query_data.split("_", 1)[1]
            log.info(f"User selected leech type: {leech_type}")
            BOT.Mode.type = leech_type
            if message: await message.delete() # Delete leech type selection message

            # --- REMOVED PASSWORD ASKING LOGIC FOR SIMPLICITY ---
            # Assuming passwords are set via commands /zipaswd /unzipaswd if needed

            # Directly schedule the task
            log.info("Proceeding to start task...")
            try: # Send status to OWNER
                # Ensure keyboard() is imported or defined if used here
                status_msg_obj = await client.send_message(OWNER, "#STARTING_TASK\n\n**Task commencing...**", reply_markup=keyboard())
                MSG.status_msg = status_msg_obj
            except Exception as start_err:
                log.error(f"Failed send status msg: {start_err}", exc_info=True)
                if message: await client.send_message(chat_id, "❌ Failed initialize task status.")
                BOT.State.started = False; BOT.State.task_going = False; return

            BOT.State.task_going = True; BOT.State.started = False; reply_prompt_message_id = None;
            BOT.TASK = asyncio.create_task(taskScheduler())
            # --- END REMOVED PASSWORD ASKING LOGIC ---

        # --- REMOVED Password Skipping Callbacks ---
        # Assuming passwords are now handled via commands only

        # --- Settings Callbacks ---
        # <<< THIS BLOCK'S INDENTATION MUST MATCH THE PREVIOUS BLOCKS >>>
        # Add settings callbacks here with correct indentation
        # Example:
        elif query_data == "setting_refresh":
             await callback_query.answer("Refreshing settings...")
             await send_settings(client, message, msg_id, False)
        elif query_data == "media":
             BOT.Options.stream_upload = True; BOT.Setting.stream_upload = "Media"
             await callback_query.answer("Uploading As Media", show_alert=False)
             await send_settings(client, message, msg_id, False)
        elif query_data == "document":
             BOT.Options.stream_upload = False; BOT.Setting.stream_upload = "Document"
             await callback_query.answer("Uploading As Document", show_alert=False)
             await send_settings(client, message, msg_id, False)
        # ... add other settings callbacks like "video", "caption", "thumb", "set-prefix", "set-suffix", "close", "back" ...
        # Ensure they all start with 'elif' and have the same indentation as the main 'if'/'elif' blocks
        elif query_data == "close":
            await callback_query.answer("Settings closed")
            await message.delete()
        elif query_data == "back":
            await callback_query.answer()
            await send_settings(client, message, msg_id, False)

        # --- Task Cancellation ---
        # <<< THIS BLOCK'S INDENTATION MUST MATCH THE PREVIOUS BLOCKS >>>
        elif query_data == "cancel":
            try:
                await callback_query.answer("Task Cancelled!", show_alert=True)
            except Exception:
                await callback_query.answer("Cancelling...") # Fallback answer
            log.info("Task cancellation requested by user via button.")
            if BOT.State.started and not BOT.State.task_going:
                log.info("Cancelling task during setup phase.")
                BOT.State.started = False; reply_prompt_message_id = None;
                if message: await message.delete() # Delete the message with the cancel button
                # Reset states fully
                TaskError.reset(); TRANSFER.reset(); BOT.SOURCE = []; BOT.Options.filenames = []
            elif BOT.State.task_going:
                log.info("Calling cancelTask for running task.")
                await cancelTask("User pressed Cancel button.")
                # cancelTask handles deleting the status message
            else:
                log.info("Cancel pressed but no task/setup active.")
                if message: await message.delete() # Delete the message if it exists

        # --- Fallback for Unknown Callbacks ---
        # <<< THIS BLOCK'S INDENTATION MUST MATCH THE PREVIOUS BLOCKS >>>
        else:
            log.warning(f"Unhandled callback query data: {query_data}")
            await callback_query.answer("Unknown action!", show_alert=True)

    # This 'except' MUST be aligned with the 'try' block at the start of the function
    except Exception as e:
        log.error(f"Error handling callback {query_data}: {e}", exc_info=True)
        try:
            await callback_query.answer("An error occurred!", show_alert=True)
        except Exception: pass # Ignore if answering fails too
        # Reset state fully on unhandled error
        BOT.State.started = False; BOT.State.task_going = False; reply_prompt_message_id = None;
        if TaskError: TaskError.reset()
        if TRANSFER: TRANSFER.reset()
        BOT.SOURCE = []; BOT.Options.filenames = []

# --- End handle_options function ---
# Image Handler (handle_image - remains the same)
@colab_bot.on_message(filters.photo & filters.private)
async def handle_image(client, message):
    log.info(f"Received photo from user {message.from_user.id}, setting thumbnail.")
    msg = await message.reply_text("<i>Trying To Save Thumbnail...</i>")
    success = await setThumbnail(message)
    if success: await msg.edit_text("**Thumbnail Changed ✅**"); await message.delete()
    else: await msg.edit_text("🥲 **Couldn’t set thumbnail...**", quote=True)
    await sleep(5); await message_deleter(None, msg)

# Other Command Handlers (setname, zipaswd, unzipaswd, help - remain the same)
@colab_bot.on_message(filters.command("setname") & filters.private)
async def custom_name(client, message):
    global BOT; log.info("Received /setname command.")
    if len(message.command) != 2: msg = await message.reply_text("Send\n/setname <code>custom_fileame.extension</code>", quote=True)
    else: BOT.Options.custom_name = message.command[1]; msg = await message.reply_text("Custom Name Set!"); log.info(f"Custom name: {BOT.Options.custom_name}")
    await sleep(15); await message_deleter(message, msg)
@colab_bot.on_message(filters.command("zipaswd") & filters.private)
async def zip_pswd(client, message):
    global BOT; log.info("Received /zipaswd command.")
    if len(message.command) != 2: msg = await message.reply_text("Send\n/zipaswd <code>password</code>", quote=True)
    else: BOT.Options.zip_pswd = message.command[1]; msg = await message.reply_text("Zip Password Set!"); log.info("Zip password set.")
    await sleep(15); await message_deleter(message, msg)
@colab_bot.on_message(filters.command("unzipaswd") & filters.private)
async def unzip_pswd(client, message):
    global BOT; log.info("Received /unzipaswd command.")
    if len(message.command) != 2: msg = await message.reply_text("Send\n/unzipaswd <code>password</code>", quote=True)
    else: BOT.Options.unzip_pswd = message.command[1]; msg = await message.reply_text("Unzip Password Set!"); log.info("Unzip password set.")
    await sleep(15); await message_deleter(message, msg)
@colab_bot.on_message(filters.command("help") & filters.private)
async def help_command(client, message):
    log.info("Received /help command.")
    # Update help text to remove separate commands
    help_text = ("Send /start To Check If I am alive 🤨\n\n"
                 "**Download/Mirror Commands:**\n"
                 "  `/tupload` - Leech to Telegram\n"
                 "  `/gdupload` - Mirror to GDrive\n"
                 "  `/ytupload` - Leech YouTube-DL links\n"
                 "  `/drupload` - Leech from Colab directory\n"
                 "Follow prompts after command (you'll be asked to select service type for /tupload & /gdupload).\n\n"
                 "**Other Commands:** `/settings`, `/setname`, `/zipaswd`, `/unzipaswd`\n\n"
                 "⚠️ **Send image for Thumbnail!**")
    await message.reply_text(help_text, quote=True, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Instructions 📖", url="https://github.com/XronTrix10/Telegram-Leecher/wiki/INSTRUCTIONS")],[InlineKeyboardButton("Channel 📣", url="https://t.me/Colab_Leecher"), InlineKeyboardButton("Group 💬", url="https://t.me/Colab_Leecher_Discuss")]]))

# Main Execution Guard
if __name__ == "__main__":
     log.info("Colab Leecher Script Starting as main...")
     # Start the web server in a daemon thread.  Any failures during
     # startup are logged but do not prevent the bot from running.
     try:
         threading.Thread(target=run_server, name="WebServer", daemon=True).start()
         log.info("Web server started successfully in background thread.")
     except Exception as e:
         log.error(f"Failed to start web server: {e}")
     if colab_bot:
          log.info("colab_bot instance found, attempting run()...")
          try: colab_bot.run()
          except Exception as run_err: log.critical(f"Bot crashed during run: {run_err}", exc_info=True)
     else: log.critical("colab_bot was not initialized successfully.")