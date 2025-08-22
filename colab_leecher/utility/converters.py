# /content/Telegram-Leecher/colab_leecher/utility/converters.py
import os
import re
import json
import math
import GPUtil
import shutil
import logging 
import subprocess
import asyncio 
from threading import Thread
from datetime import datetime
from os import makedirs, path as ospath
try:
    from moviepy.editor import VideoFileClip as VideoClip
except ImportError:
    VideoClip = None 

from .variables import BOT, MSG, BotTimes, Paths, Messages, TaskError, TRANSFER
from .helper import (
    getSize,fileType,keyboard, multipartArchive, sizeUnit,speedETA,status_bar,sysINFO,getTime
)

log = logging.getLogger(__name__)

async def archive(path: str, remove: bool, max_split_size_bytes: int) -> tuple[str | None, int]:  # Returns (path, size) or (None, 0)
    """
    Create a ZIP archive of a file or directory without invoking external tools.

    This implementation replaces the previous 7‑Zip based solution which
    relied on ``asyncio.create_subprocess_shell`` and unsanitised
    command strings.  Using the Python standard library avoids
    command‑injection vulnerabilities and the need for additional system
    packages.  The ``max_split_size_bytes`` argument is currently
    ignored; splitting archives is not supported in this simplified
    implementation.  On success, returns a tuple containing the path
    to the archive and its size in bytes; on failure, returns ``(None, 0)``
    and sets ``TaskError``.
    """
    import zipfile
    from pathlib import Path

    # Validate source path
    if not ospath.exists(path):
        log.error(f"Archive Error: Source path does not exist: {path}")
        TaskError.state = True
        TaskError.text = "Archive source path missing."
        return None, 0

    # Determine output name
    if BOT.Options.custom_name:
        name = BOT.Options.custom_name
    elif ospath.isfile(path):
        name, _ = ospath.splitext(ospath.basename(path))
    elif ospath.isdir(path):
        name = ospath.basename(path)
    else:
        name = Messages.download_name if Messages.download_name else "archive"
    clean_name = name.replace('/', '_')

    # Ensure temporary zip directory exists
    makedirs(Paths.temp_zpath, exist_ok=True)
    archive_out_final_name = f"{clean_name}.zip"
    archive_out_path = ospath.join(Paths.temp_zpath, archive_out_final_name)
    Messages.download_name = archive_out_final_name

    # Create the ZIP file in a background thread to avoid blocking the event loop
    def _zip_target(src: str, dst: str):
        with zipfile.ZipFile(dst, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            src_path = Path(src)
            if src_path.is_file():
                # Write a single file
                zf.write(src, arcname=src_path.name)
            else:
                # Recursively write directory contents
                for file_path in src_path.rglob('*'):
                    if file_path.is_file():
                        zf.write(str(file_path), arcname=str(file_path.relative_to(src_path)))

    try:
        # Offload heavy compression to a worker thread
        await asyncio.to_thread(_zip_target, path, archive_out_path)
    except Exception as exc:
        log.error(f"Error creating ZIP archive: {exc}", exc_info=True)
        TaskError.state = True
        TaskError.text = f"Archive error: {exc}"
        # Ensure no partial archive remains
        if ospath.exists(archive_out_path):
            try:
                os.remove(archive_out_path)
            except OSError as e:
                log.warning(f"Could not remove partial archive {archive_out_path}: {e}")
        return None, 0

    # Compute size
    final_archive_size = getSize(archive_out_path) if ospath.exists(archive_out_path) else 0
    if final_archive_size <= 0:
        log.error("Archive produced empty file.")
        TaskError.state = True
        TaskError.text = "Archive produced empty file."
        if ospath.exists(archive_out_path):
            try:
                os.remove(archive_out_path)
            except OSError as e:
                log.warning(f"Could not remove empty archive {archive_out_path}: {e}")
        return None, 0

    # Remove original source if requested
    if remove:
        log.info(f"Removing original source after archiving: {path}")
        try:
            if ospath.isfile(path):
                os.remove(path)
            elif ospath.isdir(path):
                shutil.rmtree(path)
        except Exception as rm_err:
            log.warning(f"Failed to remove original source '{path}': {rm_err}")

    return archive_out_path, final_archive_size
# ----- END OF archive function definition -----

async def videoConverter(file: str):
    global BOT, MSG, BotTimes, Messages # Make sure Messages is global if used in msg_updater

    # Nested function for moviepy conversion
    def convert_to_mp4(input_file, out_file):
        if VideoClip is None:
             log.error("Moviepy (VideoFileClip) not found, cannot convert using this method.")
             return # Cannot proceed without moviepy
        try:
            clip = VideoClip(input_file)
            # Define ffmpeg parameters if needed, check moviepy documentation
            clip.write_videofile(
                out_file,
                codec="libx264",       # Example codec
                audio_codec="aac",    # Example audio codec
                threads=4,            # Example: Use multiple threads
                logger='bar',         # Example: Show progress bar
                # ffmpeg_params=["-strict", "-2"] # Optional: Add specific ffmpeg params if necessary
            )
            clip.close() # Close the clip explicitly
        except Exception as moviepy_err:
            log.error(f"Moviepy conversion failed for {input_file}: {moviepy_err}", exc_info=True)
            # Optionally try to remove potentially corrupt output file
            if ospath.exists(out_file) and getSize(out_file) == 0:
                 try: os.remove(out_file)
                 except OSError: pass


    # Nested function to update status message
    async def msg_updater(c: int, tr, engine: str, core: str):
        # Ensure Messages is accessible (global or passed as argument)
        messg = f"╭「" + "░" * c + "█" + "░" * (11 - c) + "」"
        messg += f"\n├⏳ **Status »** __Converting 🔄__\n├🕹 **Attempt »** __{tr}__"
        messg += f"\n├⚙️ **Engine »** __{engine}__\n├💪🏼 **Handler »** __{core}__"
        messg += f"\n╰🍃 **Time Spent »** __{getTime((datetime.now() - BotTimes.start_time).seconds)}__"
        full_message = Messages.task_msg + mtext + messg + sysINFO() # Ensure mtext is defined in outer scope
        try:
            if MSG.status_msg:
                 await MSG.status_msg.edit_text(text=full_message, reply_markup=keyboard())
        except Exception as e:
             if "Message is not modified" not in str(e):
                  log.warning(f"Status update failed during conversion: {e}")

    # --- videoConverter main logic ---
    name, ext = ospath.splitext(file)
    log.info(f"Starting video conversion check for: {ospath.basename(file)}")

    # Return if It's already the target format (mp4 or mkv?)
    # This check might be too simplistic depending on desired output
    # if ext.lower() in [".mkv", ".mp4"]:
    #    log.info("File is already MKV/MP4, skipping conversion.")
    #    return file

    c, out_file, Err = 0, f"{name}.{BOT.Options.video_out}", False # Use BOT.Options for target extension
    gpu_available = len(GPUtil.getAvailable()) > 0 # Check if GPU exists

    # Example quality setting - adjust as needed
    quality = "-preset slow -crf 18" if BOT.Options.convert_quality else "-preset medium -crf 23" # Use CRF for quality

    # Determine ffmpeg command based on GPU availability
    if gpu_available:
        # Example NVENC command (adjust based on GPU and desired quality/speed)
        cmd = f'ffmpeg -y -i "{file}" -c:v h264_nvenc {quality} -c:a copy "{out_file}"'
        core = "GPU (NVENC)"
    else:
        # Example libx264 (CPU) command
        cmd = f'ffmpeg -y -i "{file}" -c:v libx264 {quality} -c:a copy "{out_file}"'
        core = "CPU (libx264)"

    mtext = f"<b>🎥 Converting Video »</b>\n\n<code>{ospath.basename(file)}</code>\n\n"
    log.info(f"Running ffmpeg (Attempt 1): {cmd}")
    proc = None
    try:
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        while proc.poll() is None:
            await msg_updater(c, "1st", "FFmpeg 🏍", core)
            c = (c + 1) % 12
            await asyncio.sleep(3) # Use asyncio.sleep

        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            log.error(f"FFmpeg (Attempt 1) failed with code {proc.returncode}.")
            if stderr: log.error(f"FFmpeg stderr:\n{stderr.decode('utf-8', errors='ignore')}")
            Err = True
        else:
            # Check output file validity even on success code 0
            if not ospath.exists(out_file) or getSize(out_file) == 0:
                log.warning("FFmpeg reported success but output file invalid/empty.")
                if ospath.exists(out_file): os.remove(out_file) # Remove empty file
                Err = True
            else:
                log.info("FFmpeg (Attempt 1) conversion successful.")
                Err = False # Conversion succeeded

    except Exception as ffmpeg_err:
        log.error(f"Error during FFmpeg (Attempt 1) execution: {ffmpeg_err}", exc_info=True)
        if proc and proc.poll() is None: proc.kill()
        Err = True

    # --- Attempt 2 (Moviepy) only if FFmpeg failed AND moviepy is available ---
    if Err and VideoClip is not None:
        log.warning("FFmpeg failed, attempting conversion with Moviepy (CPU)...")
        moviepy_success = False
        try:
            # Run moviepy conversion in a separate thread to avoid blocking asyncio loop
            # Use ThreadPoolExecutor for better management if doing many conversions
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, convert_to_mp4, file, out_file)

            # Check result after thread finishes
            if ospath.exists(out_file) and getSize(out_file) > 0:
                 log.info("Moviepy conversion successful.")
                 moviepy_success = True
            else:
                 log.error("Moviepy conversion failed or produced empty file.")
                 if ospath.exists(out_file): os.remove(out_file)
                 moviepy_success = False

        except Exception as thread_err:
             log.error(f"Error running Moviepy conversion in executor: {thread_err}", exc_info=True)
             moviepy_success = False

        # Update Err based on moviepy result
        Err = not moviepy_success


    # Final decision based on Err status
    if Err:
        log.error(f"Video conversion failed for {ospath.basename(file)} after all attempts.")
        return file # Return original file path if conversion failed
    else:
        log.info(f"Video conversion successful. Output: {ospath.basename(out_file)}")
        # Remove original file after successful conversion
        try:
             if ospath.exists(file): os.remove(file)
        except OSError as e:
             log.warning(f"Could not remove original file {file} after conversion: {e}")
        return out_file # Return new converted file path

# Replace sizeChecker in colab_leecher/utility/converters.py
# Ensure necessary imports: log, ospath, os, BOT, Paths, archive, splitVideo, splitArchive, getSize, sizeUnit, fileType, TaskError, asyncio

async def sizeChecker(file_path, remove: bool) -> bool:
    global Paths, BOT, TaskError, log

    log.info(f"sizeChecker started for: {ospath.basename(file_path)}")
    max_size_bytes = 1900 * 1024 * 1024
    target_video_split_mb = 1500

    file_size = 0
    try:
        if ospath.exists(file_path): file_size = os.stat(file_path).st_size
        else: log.warning(f"sizeChecker: Input file does not exist: {file_path}"); return False
    except OSError as e: log.error(f"sizeChecker: Cannot stat input file {file_path}: {e}"); return False

    if file_size > max_size_bytes:
        log.info(f"File size {sizeUnit(file_size)} exceeds {sizeUnit(max_size_bytes)} limit. Processing required.")
        _, filename = ospath.split(file_path)
        _, extension = ospath.splitext(filename)
        ext_lower = extension.lower()
        processing_done = False

        # Check if MP4 or MKV
        if ext_lower in ['.mp4', '.mkv']:
            if BOT.Options.is_split:
                log.info(f"File '{filename}' is MP4/MKV > limit. Splitting video.")
                await splitVideo(file_path, target_video_split_mb, remove) # Assumes splitVideo sets TaskError
                processing_done = True
            else:
                # Archive MP4/MKV if splitting is off
                log.info(f"File '{filename}' is MP4/MKV > limit, but video splitting is OFF. Archiving instead.")
                # <<< --- Get path AND size from archive --- >>>
                archive_output_path, archive_size = await archive(file_path, remove, max_size_bytes)
                # <<< --- Check TaskError and path --- >>>
                if TaskError.state or not archive_output_path:
                     log.error(f"Archiving failed for MP4/MKV '{filename}'. Skipping further processing.")
                     processing_done = True # Mark as attempted
                else:
                     log.info(f"Archiving MP4/MKV succeeded. Output: {archive_output_path}, Size: {sizeUnit(archive_size)}")
                     processing_done = True
                     # <<< --- Check returned archive_size for splitting --- >>>
                     if archive_size > max_size_bytes:
                          log.info(f"MP4/MKV archive size {sizeUnit(archive_size)} exceeds limit. Splitting archive...")
                          await splitArchive(archive_output_path, max_size_bytes) # Assumes splitArchive sets TaskError
                          if TaskError.state: log.error(f"splitArchive failed. Reason: {TaskError.text}")
                     else: log.info("Created archive size is within limit. No splitting needed.")
        else:
            # Not MP4/MKV: Archive it first
            log.info(f"File '{filename}' is > limit and not MP4/MKV. Archiving first...")
            # <<< --- Get path AND size from archive --- >>>
            archive_output_path, archive_size = await archive(file_path, remove, max_size_bytes)

            # <<< --- Check TaskError and path --- >>>
            if TaskError.state or not archive_output_path:
                 log.error(f"Archiving failed for '{filename}'. Skipping further processing. Reason: {TaskError.text if TaskError.text else 'Archive function failed.'}")
                 processing_done = True
            else:
                 log.info(f"Archiving succeeded. Output: {archive_output_path}, Size: {sizeUnit(archive_size)}")
                 # <<< --- Check returned archive_size for splitting --- >>>
                 if archive_size > max_size_bytes:
                     log.info(f"Archive size {sizeUnit(archive_size)} exceeds limit. Splitting archive...")
                     await splitArchive(archive_output_path, max_size_bytes) # Assumes splitArchive sets TaskError
                     if TaskError.state: log.error(f"splitArchive failed. Reason: {TaskError.text}")
                 elif archive_size <= 0: # Check if size is invalid
                     log.error("Archive size reported as 0 B by archive function. Cannot proceed.")
                     if not TaskError.state: TaskError.state = True; TaskError.text = "Created archive size is 0 B."
                 else:
                     log.info("Created archive size is within limit. No splitting needed.")
                 processing_done = True

        # await asyncio.sleep(0.5) # Delay likely not needed now
        return processing_done
    else:
        # File size is within limit
        return False

# Replace archive in colab_leecher/utility/converters.py
# Ensure necessary imports: log, os, ospath, subprocess, shutil, BOT, Messages, Paths, BotTimes, MSG, TaskError, getSize, sizeUnit, speedETA, status_bar, getTime, makedirs, asyncio

# ----- extract FUNCTION -----

async def extract(zip_filepath, remove: bool):
    # Ensure necessary globals and imports are accessible
    global BOT, Paths, Messages, BotTimes, MSG, log, TaskError, getSize, sizeUnit, multipartArchive, speedETA, status_bar, getTime, makedirs, os, ospath, subprocess, shutil, re

    extract_success = False
    final_extracted_path = None
    error_reason = "Extraction failed"

    if not ospath.exists(zip_filepath):
        log.error(f"Extract Error: Input file does not exist: {zip_filepath}")
        TaskError.state = True; TaskError.text = f"Extract source missing: {ospath.basename(zip_filepath)}"
        return False

    dir_path, filename = ospath.split(zip_filepath)
    Messages.status_head = f"<b>📂 EXTRACTING »</b>\n\n<code>{filename}</code>\n"

    password = BOT.Options.unzip_pswd # Get potential password

    name, ext = ospath.splitext(filename)
    ext_lower = ext.lower()
    file_pattern = ""
    real_name = name
    temp_unzip_path = Paths.temp_unzip_path
    total_size_bytes = 0
    command_list = None # Use a list for command and args

    os.makedirs(temp_unzip_path, exist_ok=True)

    # --- Determine command list based on extension ---
    if ext_lower == ".rar":
        command_list = ['unrar', 'e', '-kb', '-o+', '-y'] # Base command
        if password: command_list.append(f'-p{password}') # Add password arg IF set
        command_list.extend([zip_filepath, temp_unzip_path + os.sep]) # Add file and target dir
        if ".part" in name.lower(): file_pattern = "rar"
    elif ext_lower in [".tar", ".tar.gz", ".tgz"]:
        if ext_lower == ".tar": command_list = ['tar', '-xf', zip_filepath, '-C', temp_unzip_path]
        else: command_list = ['tar', '-xzf', zip_filepath, '-C', temp_unzip_path]
    elif ext_lower in [".zip", ".7z", ".001", ".z01"]:
         # Note: 7z syntax for password is -pPassword (no space)
         command_list = ['7z', 'x', f'-o{temp_unzip_path}', '-y'] # Base command for 7z
         if password: command_list.append(f'-p{password}') # Add password arg IF set
         command_list.append(zip_filepath) # Add input file path
         if ext_lower == ".001": file_pattern = "7z"
         elif ext_lower == ".z01": file_pattern = "zip"
    else:
         log.error(f"Unsupported archive extension for extraction: '{ext_lower}'")
         TaskError.state = True; TaskError.text = f"Unsupported archive type: {ext_lower}"
         return False

    # Calculate total size (handle multipart)
    try:
        # ... (size calculation logic remains same) ...
        if not file_pattern:
            total_size_bytes = getSize(zip_filepath)
            real_name, _ = ospath.splitext(filename)
        else:
            real_name, total_size_bytes = multipartArchive(zip_filepath, file_pattern, False)
        total_size_str = sizeUnit(total_size_bytes) if total_size_bytes > 0 else "N/A"
        Messages.download_name = real_name
        Messages.status_head = f"<b>📂 EXTRACTING »</b>\n\n<code>{real_name}{ext}</code>\n"
    except Exception as size_err:
        log.error(f"Error calculating archive size for {filename}: {size_err}")
        total_size_str = "N/A"

    if not command_list:
         log.error(f"Extraction command list could not be determined for {filename}.")
         TaskError.state = True; TaskError.text = f"Cannot determine extract command for {filename}"
         return False

    log.info(f"Running Extractor Command List: {command_list}") # Log the list itself for clarity
    BotTimes.task_start = datetime.now()
    proc = None
    try:
        # --- Execute command using list, shell=False (default) ---
        # Ensure shell=False is implicitly used by passing a list
        proc = subprocess.run(command_list, capture_output=True, text=True, check=False)

        exit_code = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr

        if stdout: log.info(f"Extractor stdout:\n{stdout}")
        # Log stderr even if exit code is 0, as some tools print warnings there
        if stderr: log.error(f"Extractor stderr:\n{stderr}")

        if exit_code == 0:
            log.info(f"Extraction completed successfully (code 0) for '{filename}'.")
            extract_success = True
            # ... (determine final_extracted_path logic remains same) ...
            extracted_items = os.listdir(temp_unzip_path)
            if len(extracted_items) == 1:
                 final_extracted_path = ospath.join(temp_unzip_path, extracted_items[0])
            else:
                 final_extracted_path = temp_unzip_path
        else:
            error_reason = f"Extractor failed code {exit_code}."
            # Prioritize getting last line of stderr for concise error reporting
            if stderr:
                 last_stderr_line = stderr.strip().splitlines()[-1] if stderr.strip() else 'None'
                 error_reason += f" Stderr: {last_stderr_line}"
            log.error(f"Extraction failed for '{filename}'. Reason: {error_reason}")
            extract_success = False
            TaskError.state = True
            TaskError.text = error_reason

    except FileNotFoundError as fnf_error:
         log.error(f"Extraction command not found: {command_list[0]}. Ensure it's installed. Error: {fnf_error}", exc_info=True)
         TaskError.state = True
         TaskError.text = f"Extractor command '{command_list[0]}' not found."
         extract_success = False
    except Exception as extract_run_err:
        log.error(f"Error running extraction process for {filename}: {extract_run_err}", exc_info=True)
        TaskError.state = True
        TaskError.text = f"Extractor runtime error: {str(extract_run_err)[:50]}"
        extract_success = False


    # Remove original archive(s) if extraction was successful *and* requested
    if extract_success and remove:
        # ... (removal logic remains same) ...
        log.info(f"Removing original archive(s) after successful extraction: {filename}")
        multipartArchive(zip_filepath, file_pattern, True)
        if ospath.exists(zip_filepath):
            try: os.remove(zip_filepath)
            except OSError as rm_err: log.warning(f"Could not remove archive trigger file {zip_filepath}: {rm_err}")

    # Return success status
    return extract_success
# ----- END OF THE FUNCTION -----

# --- splitArchive (Needs status return ideally) ---
async def splitArchive(file_path, max_size_bytes) -> bool:
    global Paths, BOT, MSG, Messages, BotTimes, TaskError, log

    split_success = False
    if not ospath.exists(file_path) or not ospath.isfile(file_path):
         log.error(f"splitArchive Error: Input file missing or invalid: {file_path}")
         TaskError.state = True; TaskError.text = f"Archive splitting source missing: {ospath.basename(file_path)}"
         return False

    _, filename = ospath.split(file_path)
    # Output parts TO the temp_zpath directory
    output_base_path = ospath.join(Paths.temp_zpath, filename) 
    makedirs(Paths.temp_zpath, exist_ok=True) 

    Messages.status_head = f"<b>✂️ SPLITTING ARCHIVE » </b>\n\n<code>{filename}</code>\n"
    total_size = getSize(file_path)
    total_size_str = sizeUnit(total_size) if total_size > 0 else "N/A"
    log.info(f"Splitting archive '{filename}' ({total_size_str}) into parts of max {sizeUnit(max_size_bytes)}")

    BotTimes.task_start = datetime.now() 
    bytes_written = 0
    part_num = 1
    error_reason = "Archive splitting failed." 

    try:
        with open(file_path, "rb") as f_in:
            while True:
                chunk = f_in.read(max_size_bytes)
                if not chunk: break

                output_filename = f"{output_base_path}.{str(part_num).zfill(3)}"
                log.debug(f"Writing part {part_num}: {output_filename}")
                with open(output_filename, "wb") as f_out: f_out.write(chunk)

                bytes_written += len(chunk)
                # --- Status Update Logic ---
                speed_string, eta, percentage = speedETA( BotTimes.task_start, bytes_written, total_size )
                await status_bar( Messages.status_head, speed_string, percentage, getTime(eta), sizeUnit(bytes_written), total_size_str, "Splitter ✂️",)
                # --- End Status Update ---
                part_num += 1
                await asyncio.sleep(0.1) 

        # Verify success
        if bytes_written >= total_size: 
             log.info(f"Archive splitting completed successfully for {filename}. Parts: {part_num - 1}")
             split_success = True
             # <<< --- ADDED LOGGING AROUND REMOVAL --- >>>
             try:
                 log.info(f"Attempting to remove original large archive after split: {file_path}")
                 os.remove(file_path)
                 log.info(f"Successfully removed original archive: {file_path}") # Log success
             except OSError as rm_err:
                 log.warning(f"Could not remove original archive {file_path} after splitting: {rm_err}")
                 # Consider if this should be treated as a failure? For now, just warn.
                 # split_success = False # Uncomment to make removal failure a task failure
             # <<< --- END ADDED LOGGING --- >>>
        else:
             log.warning(f"Archive splitting finished for {filename}, but bytes written ({bytes_written}) != total size ({total_size}).")
             error_reason = f"Split size mismatch ({bytes_written} vs {total_size})"
             split_success = False

    except IOError as io_err:
        log.error(f"I/O error during archive splitting for {filename}: {io_err}", exc_info=True)
        error_reason = f"I/O Error during split: {str(io_err)[:100]}"
        split_success = False
    except Exception as split_err:
        log.error(f"Unexpected error during archive splitting for {filename}: {split_err}", exc_info=True)
        error_reason = f"Unexpected split error: {str(split_err)[:100]}"
        split_success = False

    # Set TaskError and clean up parts if splitting failed
    if not split_success:
        TaskError.state = True
        TaskError.text = error_reason
        log.info(f"Cleaning up parts due to split failure for: {filename}")
        for i in range(1, part_num):
             part_file = f"{output_base_path}.{str(i).zfill(3)}"
             if ospath.exists(part_file):
                  try: os.remove(part_file)
                  except OSError: pass

    return split_success


# --- splitVideo (with fixes from previous steps) ---
async def splitVideo(file_path, target_segment_size_mb: int, remove: bool):
    # Returns True on success, False on failure
    global Paths, BOT, MSG, Messages, BotTimes, TaskError, log # Ensure globals accessible, add log

    log.info(f"Attempting to split video: {os.path.basename(file_path)} into segments of ~{target_segment_size_mb}MB, ensuring max ~2GB per part.")
    _, filename = ospath.split(file_path)
    just_name, extension = ospath.splitext(filename)

    # --- Get File Info ---
    bitrate = None
    duration_total_seconds = 0.0
    total_file_size = 0
    try:
        if not ospath.exists(file_path):
             log.error(f"splitVideo: Input file not found: {file_path}")
             TaskError.state = True; TaskError.text = f"Split source missing: {filename}"
             return False
        
        total_file_size = getSize(file_path) 
        if total_file_size <= 0:
             log.error(f"splitVideo: Could not get valid size for {filename}. Cannot split.")
             TaskError.state = True; TaskError.text = f"Split source size invalid: {filename}"
             return False

        cmd_probe = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", "-select_streams", "v:0", file_path] 
        output = subprocess.check_output(cmd_probe, timeout=30) 
        video_info = json.loads(output)
        
        if 'format' in video_info and 'duration' in video_info['format']:
             duration_total_seconds = float(video_info['format']['duration'])
        
        if 'streams' in video_info and len(video_info['streams']) > 0 and 'bit_rate' in video_info['streams'][0]:
             bitrate = float(video_info['streams'][0]['bit_rate'])
        elif 'format' in video_info and 'bit_rate' in video_info['format']:
             bitrate = float(video_info['format']['bit_rate'])
        
        if duration_total_seconds <= 0:
             log.warning(f"Could not determine duration for {filename}. Cannot reliably split by time.")
             TaskError.state = True; TaskError.text = f"Could not get video duration for {filename}"
             return False

        if not bitrate or bitrate <= 0:
             log.warning(f"Could not determine bitrate for {filename}. Will estimate based on size/duration.")
             bitrate = (total_file_size * 8) / duration_total_seconds 

    except subprocess.TimeoutExpired:
         log.error(f"Error: ffprobe timed out getting video metadata for {filename}")
         TaskError.state = True; TaskError.text = f"ffprobe timeout for {filename}"
         return False
    except subprocess.CalledProcessError as cpe:
         log.error(f"Error: ffprobe failed getting video metadata for {filename}. Return code: {cpe.returncode}")
         if cpe.stderr: log.error(f"ffprobe stderr: {cpe.stderr.decode('utf-8', errors='ignore')}")
         TaskError.state = True; TaskError.text = f"ffprobe failed for {filename}"
         return False
    except json.JSONDecodeError:
         log.error(f"Error: Could not parse ffprobe JSON output for {filename}")
         TaskError.state = True; TaskError.text = f"ffprobe JSON error for {filename}"
         return False
    except Exception as probe_err:
        log.error(f"Error: Could not get video metadata for {filename}: {probe_err}", exc_info=True)
        TaskError.state = True; TaskError.text = f"Metadata error for {filename}"
        return False

    # --- Calculate Segment Duration ---
    MAX_SPLIT_SIZE_BYTES = 1.5 * 1024 * 1024 * 1024 # Using 1.90 GiB
    
    min_parts_required = 1
    if total_file_size > MAX_SPLIT_SIZE_BYTES:
        min_parts_required = math.ceil(total_file_size / MAX_SPLIT_SIZE_BYTES)
    
    duration_per_part_max = float('inf') 
    if min_parts_required > 1:
        duration_per_part_max = math.floor(duration_total_seconds / min_parts_required)
        log.info(f"Min parts required based on size ({sizeUnit(total_file_size)} / {sizeUnit(MAX_SPLIT_SIZE_BYTES)}): {min_parts_required}. Max duration/part: {duration_per_part_max}s")
        
    duration_per_part_target = float('inf') 
    if bitrate > 0:
        target_size_bits = target_segment_size_mb * 1024 * 1024 * 8
        duration_per_part_target = int(target_size_bits / bitrate)
        log.info(f"Target duration per part based on bitrate ({sizeUnit(bitrate/8)}/s) and target size ({target_segment_size_mb}MB): {duration_per_part_target}s")
    else:
        log.warning("Bitrate is zero or unknown, cannot calculate target duration based on size.")

    final_segment_duration = max(10, min(duration_per_part_max, duration_per_part_target))

    if final_segment_duration >= duration_total_seconds:
         log.info(f"Final calculated segment duration ({final_segment_duration}s) >= total duration ({duration_total_seconds:.2f}s). No splitting required.")
         return True 
         
    log.info(f"Final segment duration chosen: {final_segment_duration} seconds.")
    
    # --- Execute FFmpeg Split ---
    makedirs(Paths.temp_zpath, exist_ok=True)
    cmd_split = (f'ffmpeg -i "{file_path}" -c copy -map 0:v -map 0:a? -copyts ' # <<< CORRECTED MAPPING
                 f'-segment_time {final_segment_duration} '
                 f'-f segment -reset_timestamps 1 -segment_start_number 1 '
                 f'-movflags +faststart ' 
                 f'"{Paths.temp_zpath}/{just_name}.part%03d{extension}"')

    log.info(f"Executing ffmpeg split: {cmd_split}")
    Messages.status_head = f"<b>✂️ SPLITTING » </b>\n\n<code>{filename}</code>\n"
    BotTimes.task_start = datetime.now()

    proc = None
    ffmpeg_success = False
    try:
        # Use asyncio.create_subprocess_shell for better async handling
        proc = await asyncio.create_subprocess_shell(
            cmd_split,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        total_in_unit = sizeUnit(total_file_size)
        log.info(f"Monitoring split process (PID: {proc.pid})...")

        # --- Monitor Progress with Restored Progress Bar ---
        while proc.returncode is None:
            current_split_size = getSize(Paths.temp_zpath) # Size of output dir
            
            # Calculate rough percentage based on output size (may not be accurate)
            percentage = 0
            if total_file_size > 0:
                percentage = min(100, (current_split_size / total_file_size) * 100)
            
            # Calculate speed and ETA based on output size change (also rough)
            # speed_string, eta_seconds, _ = speedETA(BotTimes.task_start, current_split_size, total_file_size)
            # eta_str = getTime(eta_seconds) 
            # Note: Speed/ETA based on output dir size is very inaccurate for splitting. 
            #       Let's omit them for now and just show the bar and elapsed time.
            elapsed_time_str = getTime((datetime.now() - BotTimes.task_start).seconds)

            # Call status_bar WITHOUT use_custom_text=True to show the bar
            # Provide necessary parameters, using "N/A" for less reliable ones like speed/ETA
            await status_bar(
                down_msg=Messages.status_head, 
                speed="N/A", # Speed is unreliable here
                percentage=percentage, # Use rough percentage for bar
                eta="N/A", # ETA is unreliable here
                done=sizeUnit(current_split_size), # Show current output size
                total_size=total_in_unit, # Show original total size
                engine="Splitter ✂️" 
                # removed use_custom_text=True
            )
            
            # Check process status without blocking excessively
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0) # Wait for 2s
            except asyncio.TimeoutError:
                pass # Process still running, continue loop
        # --- End Monitoring Loop ---

        # Process finished, get final results
        stdout, stderr = await proc.communicate() # Get remaining output
        log.info(f"Split process finished with return code: {proc.returncode}")
        
        # --- Check success based on return code and output files ---
        if proc.returncode == 0:
            segment_files = [f for f in os.listdir(Paths.temp_zpath) if f.startswith(f"{just_name}.part") and f.endswith(extension)]
            if segment_files:
                 log.info(f"FFmpeg split completed successfully for {filename}. Segments found: {len(segment_files)}")
                 ffmpeg_success = True
                 total_parts_size = getSize(Paths.temp_zpath)
                 if abs(total_parts_size - total_file_size) > total_file_size * 0.1:
                      log.warning(f"Total size of split parts ({sizeUnit(total_parts_size)}) differs significantly from original ({total_in_unit}). Check results.")
            else:
                 log.error(f"FFmpeg split finished with code 0 but no segment files found for {filename} in {Paths.temp_zpath}.")
                 if stderr: log.error(f"FFmpeg stderr:\n{stderr.decode('utf-8', errors='ignore')}")
                 TaskError.state = True; TaskError.text = f"Split failed (no output files): {filename}"
                 ffmpeg_success = False
        else:
            log.error(f"FFmpeg split failed for {filename} with return code {proc.returncode}.")
            if stderr: log.error(f"FFmpeg stderr:\n{stderr.decode('utf-8', errors='ignore')}")
            TaskError.state = True; TaskError.text = f"Split failed (ffmpeg code {proc.returncode}): {filename}"
            ffmpeg_success = False

    except asyncio.TimeoutError: # Should not happen with wait_for loop logic, but keep as fallback
         log.error(f"Error: ffmpeg process communication timed out during split for {filename}")
         if proc and proc.returncode is None: await kill_proc(proc) # Use helper to kill
         TaskError.state = True; TaskError.text = f"Split communication timeout for {filename}"
         ffmpeg_success = False
    except Exception as split_err:
        log.error(f"Error during ffmpeg execution for {filename}: {split_err}", exc_info=True)
        if proc and proc.returncode is None: await kill_proc(proc) # Use helper to kill
        TaskError.state = True; TaskError.text = f"Split execution error for {filename}"
        ffmpeg_success = False

    # Clean up original file if successful AND remove=True
    if ffmpeg_success and remove:
        try:
            if ospath.exists(file_path):
                os.remove(file_path)
                log.info(f"Removed original file after successful split: {filename}")
        except OSError as rm_err:
            log.warning(f"Could not remove original file {filename} after split: {rm_err}")

    if not ffmpeg_success and not TaskError.state:
        TaskError.state = True
        TaskError.text = TaskError.text or f"Video splitting failed for {filename}"

    return ffmpeg_success

async def kill_proc(proc):
    """Helper to terminate/kill asyncio subprocess"""
    if proc is None or proc.returncode is not None: return
    log.warning(f"Attempting to terminate/kill process PID: {proc.pid}")
    try: 
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=5) # Wait briefly for termination
        log.info(f"Process {proc.pid} terminated.")
    except asyncio.TimeoutError:
        log.warning(f"Process {proc.pid} did not terminate gracefully, killing...")
        try: 
            proc.kill()
            await proc.wait() # Wait for kill
            log.info(f"Process {proc.pid} killed.")
        except ProcessLookupError: log.info(f"Process {proc.pid} already gone.")
        except Exception as kill_err: log.error(f"Error killing process {proc.pid}: {kill_err}")
    except ProcessLookupError: log.info(f"Process {proc.pid} already gone.")
    except Exception as term_err: log.error(f"Error terminating process {proc.pid}: {term_err}")


# --- You will also need this helper function if you don't have it ---
# Add it somewhere in converters.py or helper.py and import it in converters.py
async def kill_proc(proc):
    """Helper to terminate/kill asyncio subprocess"""
    if proc is None or proc.returncode is not None: return
    log = logging.getLogger(__name__) # Get logger inside function if needed
    log.warning(f"Attempting to terminate/kill process PID: {proc.pid}")
    try: 
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=5) # Wait briefly for termination
        log.info(f"Process {proc.pid} terminated.")
    except asyncio.TimeoutError:
        log.warning(f"Process {proc.pid} did not terminate gracefully, killing...")
        try: 
            proc.kill()
            await proc.wait() # Wait for kill
            log.info(f"Process {proc.pid} killed.")
        except ProcessLookupError: log.info(f"Process {proc.pid} already gone.")
        except Exception as kill_err: log.error(f"Error killing process {proc.pid}: {kill_err}")
    except ProcessLookupError: log.info(f"Process {proc.pid} already gone.")
    except Exception as term_err: log.error(f"Error terminating process {proc.pid}: {term_err}")
