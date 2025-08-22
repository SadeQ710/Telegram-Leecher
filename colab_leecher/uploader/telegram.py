#/content/Telegram-Leecher/colab_leecher/uploader/telegram.py
import time 
import logging
import math
import os
import asyncio 
import socket 
import aiohttp 
from PIL import Image
from os import path as ospath
from datetime import datetime
from pyrogram.errors import FloodWait, SlowmodeWait 
from ..utility.variables import BOT, BotTimes, Messages, MSG, Paths, TRANSFER, TaskError
from ..utility import helper
from .. import colab_bot, OWNER, DUMP_ID

log = logging.getLogger(__name__)


RETRYABLE_EXCEPTIONS = (
    FloodWait,
    SlowmodeWait,
    TimeoutError,            
    socket.timeout,          
    aiohttp.ClientError,     
)



async def upload_file(file_path: str, display_name: str) -> bool:
    """Uploads a single file or directory contents recursively to Telegram."""
    # Ensure necessary globals are accessible within the function if needed elsewhere,
    # but prefer passing/returning values where possible.
    # Globals required by helper functions or direct use: log, BOT, Paths, TRANSFER, TaskError, DUMP_ID, OWNER, colab_bot

    if not ospath.exists(file_path):
        log.error(f"Upload Error: File/Dir does not exist: {file_path}")
        failed_info = {"link": "N/A", "filename": display_name, "index": "Upload", "reason": "Source file/dir missing"}
        if TaskError: TaskError.failed_links.append(failed_info)
        return False

    base_upload_name = display_name
    actual_upload_filename = ospath.basename(file_path)
    file_size = helper.getSize(file_path)

    # Check for zero-byte file
    if file_size == 0:
        log.error(f"Upload Error: Skipping zero-byte file: {actual_upload_filename}")
        failed_info = {"link": "N/A", "filename": base_upload_name, "index": "Upload", "reason": "Zero-byte file"}
        if TaskError: TaskError.failed_links.append(failed_info)
        return False

    log.info(f"Preparing to upload: {actual_upload_filename} (Display Name: {base_upload_name}) Size: {helper.sizeUnit(file_size)}")

    # --- Thumbnail, duration, dimension, caption logic ---
    thumb_path = None # Initialize to None, will be set later
    duration = 0
    width = 0
    height = 0
    f_type = helper.fileType(file_path)
    is_video = (f_type == "video")
    is_photo = (f_type == "photo")

    # --- Logic for Videos (Thumb & Duration) ---
    if is_video:
        # Check if it's a split file part
        if helper.is_split_file(actual_upload_filename):
            log.info(f"Split file detected: {actual_upload_filename}, using default thumbnail and duration 0.")
            thumb_path = Paths.DEFAULT_HERO # Use default thumb path initially
            duration = 0
        else:
            # Not a split file, try extracting duration and thumbnail separately
            log.debug(f"Attempting duration extraction for video: {actual_upload_filename}")
            duration = await helper.get_video_duration(file_path) # Call new duration function
            log.debug(f"Duration extraction attempt complete. Duration: {duration}")

            log.debug(f"Attempting thumbnail generation for video: {actual_upload_filename}")
            # Define a temporary directory for thumbs (ensure it exists and is writable)
            # Using /tmp is common, but adjust if needed for your environment
            temp_thumb_dir = "/tmp/colab_leecher_thumbs"
            thumb_path = await helper.get_video_thumbnail(file_path, output_dir=temp_thumb_dir) # Call new thumb function
            log.debug(f"Thumbnail generation attempt complete. Raw thumb path: {thumb_path}")

            # If thumb generation failed, fall back to default path
            if not thumb_path:
                log.warning(f"Thumbnail generation failed for {actual_upload_filename}, using default path.")
                thumb_path = Paths.DEFAULT_HERO
            # Note: Dimensions (width/height) are not extracted in this flow yet.
            # You would need another ffprobe/ffmpeg call if needed, similar to duration extraction.

    # --- Logic for Photos (Thumb is the photo itself) ---
    elif is_photo:
         thumb_path = file_path # Use the photo itself as the thumbnail for send_document fallback

    # --- Common Thumbnail Processing & Final Validation (for Videos and Photos) ---
    # Applies conversion/validation if a thumb_path was determined above
    initial_thumb_path = thumb_path # Keep track of the path before conversion/validation
    log.debug(f"Initial thumb path before final checks: {initial_thumb_path}")

    if initial_thumb_path and isinstance(initial_thumb_path, str) and ospath.exists(initial_thumb_path):
        # Try to convert/verify the image (convertIMG returns None on failure)
        log.debug(f"Attempting conversion/verification for: {initial_thumb_path}")
        # Ensure helper.convertIMG exists and is imported/accessible
        try:
            converted_path = helper.convertIMG(initial_thumb_path)
        except Exception as img_err:
             log.error(f"Error calling helper.convertIMG: {img_err}")
             converted_path = None # Treat error as conversion failure

        if converted_path and ospath.exists(converted_path):
            # Use converted path if successful
            log.debug(f"Conversion successful/verified, using: {converted_path}")
            thumb_path = converted_path
        elif ospath.exists(initial_thumb_path):
            # If conversion failed but the original exists, use default as fallback
            log.warning(f"Thumbnail conversion failed for {initial_thumb_path}, using default.")
            thumb_path = Paths.DEFAULT_HERO
        else:
            # Conversion failed AND original is now missing
            log.warning(f"Thumbnail conversion failed and original missing ({initial_thumb_path}), using default.")
            thumb_path = Paths.DEFAULT_HERO
    else:
        # The initial path (e.g., DEFAULT_HERO from split file logic) wasn't valid or didn't exist
        if initial_thumb_path: # Log if there was an initial path specified but it didn't exist
             log.warning(f"Initial thumbnail path ({initial_thumb_path}) not found, using default.")
        # No need for else here, if initial_thumb_path was None, it remains None unless default is explicitly set
        # If it wasn't video/photo, or was split file, ensure default is considered
        if thumb_path is None or not ospath.exists(thumb_path):
             thumb_path = Paths.DEFAULT_HERO # Fallback to default path string if needed

    # --- Final Validation ---
    # Check if the chosen thumb_path (even if it's DEFAULT_HERO) actually exists.
    if not thumb_path or not isinstance(thumb_path, str) or not ospath.exists(thumb_path):
         if thumb_path: # Log if we had a path but it was invalid/missing
             log.warning(f"Final chosen thumbnail path ({thumb_path}) is invalid or file missing. Setting thumb to None for upload.")
         else: # Log if thumb_path was already None
             log.debug("Thumbnail path is None after processing. No thumb will be used for upload.")
         thumb_path = None # Set to None if no valid file found

    # --- Define Caption ---
    # Ensure caption is defined *after* all thumbnail logic
    try:
         caption = f"<code>{BOT.Setting.prefix or ''}{base_upload_name}{BOT.Setting.suffix or ''}</code>"
    except Exception as cap_err:
         log.error(f"Error formatting caption: {cap_err}. Using default.")
         caption = f"<code>{base_upload_name}</code>" # Basic fallback caption

    # --- Initialize Upload State Variables ---
    # ** This block MUST be indented correctly **
    upload_success = False
    sent_message = None
    last_progress_time = 0
    retry_count = 0
    max_retries = 4 # Consider making this configurable
    error_reason = "Upload Failed"
    upload_start_time = 0 # Will be set before each attempt

    # --- Define Progress Callback ---
    # ** This 'async def' MUST be indented correctly **
    async def up_progress(current, total):
        # Indentation here is relative to the 'async def' line
        nonlocal last_progress_time, upload_start_time, base_upload_name # Ensure access to outer scope vars if needed
        now = time.time()
        # Throttle progress updates
        if now - last_progress_time > 2.5: # Update interval (e.g., 2.5 seconds)
            last_progress_time = now
            try:
                speed_string, eta_seconds, percentage = helper.speedETA(upload_start_time, current, total)
                done_str = helper.sizeUnit(current)
                total_str = helper.sizeUnit(total)
                eta_str = helper.getTime(eta_seconds)

                status_head = f"<b>📤 UPLOADING » </b>\n\n<b>🏷️ Name » </b><code>{base_upload_name}</code>\n"
                log.debug(f"up_progress: Calling status_bar. Speed='{speed_string}', Pct={percentage:.1f}, ETA='{eta_str}', Done='{done_str}', Total='{total_str}'")
                # Assuming helper.status_bar exists and handles these args
                await helper.status_bar(status_head, speed_string, percentage, eta_str, done_str, total_str, "TG Upload 🚀")
            except Exception as progress_err:
                log.warning(f"Error updating progress bar: {progress_err}")

    # --- Start Upload Attempt Loop ---
    # ** This 'while' loop MUST be indented correctly **
    while retry_count <= max_retries:
        # Indentation here is relative to the 'while' line
        try:
            upload_start_time = time.time() # Reset timer for each attempt
            last_progress_time = 0 # Reset progress throttle timer

            # Determine target chat ID (use DUMP_ID if set, otherwise OWNER)
            target_chat_id = DUMP_ID if DUMP_ID else OWNER
            if not target_chat_id:
                 log.error("Cannot upload: Neither DUMP_ID nor OWNER is set.")
                 error_reason = "Target chat ID not configured"
                 break # Exit loop if no target
            if target_chat_id == OWNER and not DUMP_ID:
                 log.warning("DUMP_ID not set, uploading to OWNER.")

            log.debug(f"Upload attempt {retry_count + 1}/{max_retries + 1} for {actual_upload_filename} to chat {target_chat_id}. Thumb: {thumb_path}")

            # --- Select Pyrogram Upload Method ---
            if BOT.Options.stream_upload and is_video:
                log.debug(f"Calling send_video for {actual_upload_filename}...")
                sent_message = await colab_bot.send_video(
                    chat_id=target_chat_id,
                    video=file_path,
                    caption=caption,
                    progress=up_progress,
                    duration=duration,
                    width=width,      # Note: width/height extraction not implemented yet
                    height=height,    # Note: width/height extraction not implemented yet
                    thumb=thumb_path,
                    supports_streaming=True
                )
                log.debug(f"send_video call returned for {actual_upload_filename}. Message received: {bool(sent_message)}")
            elif not BOT.Options.stream_upload and is_photo:
                # Use send_photo only if explicitly NOT stream_upload AND it's a photo
                log.debug(f"Calling send_photo for {actual_upload_filename}...")
                sent_message = await colab_bot.send_photo(
                    chat_id=target_chat_id,
                    photo=file_path,
                    caption=caption,
                    progress=up_progress
                )
                log.debug(f"send_photo call returned for {actual_upload_filename}. Message received: {bool(sent_message)}")
            else:
                # Default to send_document for non-videos, non-photos, or if stream_upload is False for videos
                log.debug(f"Calling send_document for {actual_upload_filename}...")
                sent_message = await colab_bot.send_document(
                    chat_id=target_chat_id,
                    document=file_path,
                    caption=caption,
                    progress=up_progress,
                    thumb=thumb_path, # send_document uses thumb too
                    force_document=True # Ensure it sends as document, not potentially photo/video
                )
                log.debug(f"send_document call returned for {actual_upload_filename}. Message received: {bool(sent_message)}")

            # --- Check Upload Result ---
            if sent_message:
                log.info(f"Successfully uploaded '{base_upload_name}' (File: {actual_upload_filename}) to chat {target_chat_id} - Msg ID: {sent_message.id}")
                # Add to transfer stats (ensure TRANSFER object exists and is handled correctly)
                try:
                    TRANSFER.sent_file.append(sent_message)
                    TRANSFER.sent_file_names.append(base_upload_name)
                    # TRANSFER.up_bytes.append(file_size) # Moved after loop success
                except AttributeError:
                    log.warning("Could not record sent file details, TRANSFER object might be missing attributes.")
                upload_success = True
                break # Exit retry loop on success
            else:
                # This case should ideally not happen if Pyrogram raises exceptions on failure
                log.error(f"Upload API call returned None for {actual_upload_filename} without throwing an exception.")
                error_reason = "Upload API call returned None"
                # Go directly to retry logic below

        except RETRYABLE_EXCEPTIONS as wait_err:
            retry_count += 1
            wait_time = 15 # Default wait
            if isinstance(wait_err, (FloodWait, SlowmodeWait)):
                wait_time = wait_err.value + 5 # Use suggested wait time + buffer
                log.warning(f"Upload for {actual_upload_filename} hit {type(wait_err).__name__}: Waiting {wait_time}s... (Attempt {retry_count}/{max_retries + 1})")
            else:
                # Exponential backoff for other retryable errors
                wait_time = min(15 * (2 ** retry_count), 180) # e.g., 30, 60, 120, 180 max
                log.warning(f"Upload for {actual_upload_filename} hit {type(wait_err).__name__}. Waiting {wait_time}s... (Attempt {retry_count}/{max_retries + 1})")

            if retry_count > max_retries:
                error_reason = f"Exceeded max retries ({max_retries + 1}) due to {type(wait_err).__name__}"
                log.error(error_reason)
                break # Exit loop after max retries

            # Update status during wait
            status_head = f"<b>📤 UPLOADING » </b>\n\n<b>🏷️ Name » </b><code>{base_upload_name}</code>\n"
            try:
                # --- MODIFIED CALL ---
                await helper.status_bar(status_head, "N/A", 0, f"Waiting {wait_time}s", "N/A", helper.sizeUnit(file_size), f"TG {type(wait_err).__name__} ⏳")
                # --- MODIFIED CALL ---
            except Exception as status_err:
                log.warning(f"Could not update status during wait: {status_err}")
            await asyncio.sleep(wait_time)
            continue # Continue to next retry attempt

        except Exception as e:
            # Non-retryable error
            error_reason = f"Non-retryable Upload Error: {str(e.__class__.__name__)} - {str(e)[:100]}"
            log.error(f"Failed to upload {actual_upload_filename} due to non-retryable error: {e}", exc_info=True)
            break # Exit loop immediately

    # --- After Retry Loop ---
    if not upload_success:
        log.error(f"Final upload status for {actual_upload_filename}: FAILED. Reason: {error_reason}")
        # Record failure (ensure TaskError exists and is handled correctly)
        failed_info = {"link": "N/A", "filename": base_upload_name, "index": "Upload", "reason": error_reason}
        try:
            if TaskError: TaskError.failed_links.append(failed_info)
        except AttributeError:
             log.warning("Could not record failed link, TaskError object might be missing attributes.")
        return False
    else:
        # Record successful upload size
        try:
            TRANSFER.up_bytes.append(file_size)
        except AttributeError:
            log.warning("Could not record uploaded bytes, TRANSFER object might be missing attributes.")
        except Exception as report_err:
            log.error(f"Error reporting uploaded bytes for {actual_upload_filename}: {report_err}")
        return True
# --- End Replacement Function ---
