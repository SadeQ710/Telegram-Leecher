#colab_leecher/downlader/aria2.py
import os
import re
import logging
import urllib.parse
import subprocess
import asyncio 
from datetime import datetime
from ..utility.helper import sizeUnit, status_bar, clean_filename, apply_dot_style, getTime, is_google_drive, is_mega # Import getTime if used by status_bar
from ..utility.variables import BOT, Aria2c, Paths, Messages, BotTimes, TaskError, TRANSFER # Import TaskError & TRANSFER

log = logging.getLogger(__name__)

# get_Aria2c_Name
def get_Aria2c_Name(link):
    # Make sure BOT is accessible
    global BOT, log
    # Return custom name if set
    if BOT.Options.custom_name: # Check directly if custom_name has value
        log.debug(f"Using custom name for Aria2c: {BOT.Options.custom_name}")
        return BOT.Options.custom_name

    # Try getting name via dry run (can be slow)
    log.debug(f"Attempting Aria2c dry run for name: {link[:100]}...")
    name = "UNKNOWN DOWNLOAD NAME" # Default
    try:
        cmd = f'aria2c -x10 --dry-run --file-allocation=none "{link}"'
        # Use subprocess.run with timeout
        result = subprocess.run(cmd, capture_output=True, shell=True, text=True, timeout=15, check=False)

        if result.returncode == 0 and result.stdout:
            # Look for 'complete:' or 'out=' lines
            match_out = re.search(r"out=([^/\n]+)\n", result.stdout) # Prefer 'out=' parameter if present
            match_comp = re.search(r"complete: (.+)\n", result.stdout) # Fallback to 'complete:'

            if match_out:
                 filename = match_out.group(1).strip()
                 log.debug(f"Got filename from 'out=': {filename}")
                 name = filename
            elif match_comp:
                 filename = match_comp.group(1).strip().split("/")[-1] # Get last part of path
                 log.debug(f"Got filename from 'complete:': {filename}")
                 name = filename
            else:
                 log.warning(f"Aria2c dry run stdout did not contain expected 'out=' or 'complete:' for {link[:100]}")
        else:
            log.warning(f"Aria2c dry run failed (Code: {result.returncode}) or no output for {link[:100]}. Stderr: {result.stderr.strip() if result.stderr else 'N/A'}")

    except subprocess.TimeoutExpired:
         log.warning(f"Aria2c dry run timed out for {link[:100]}.")
    except Exception as dry_run_err:
         log.error(f"Error during Aria2c dry run for name: {dry_run_err}")

    return name
# --- end get_Aria2c_Name ---    
# --- on_output ---
# ----- MODIFIED version of the user-provided on_output function -----
# ----- Replace the existing on_output in aria2.py with this: -----
async def on_output(output: str, current_filename: str):
    # Ensure necessary globals are accessible if needed
    global Messages, BotTimes, Aria2c, log, status_bar, sizeUnit, TaskError

    total_size = None
    downloaded_bytes = None
    percentage = None
    eta = None
    speed_string = "0B/s" # Initialize speed

    try:
        # --- FIXED Primary Regex Pattern ---
        pattern = re.compile(
            r"\[#[a-f0-9]+\s+" # Start with [# followed by hex ID and spaces
            r"(?P<downloaded>[\d\.]+[KMG]?i?B)/(?P<total>[\d\.]+[KMG]?i?B)" # Downloaded/Total
            r"\((?P<percent>[\d\.]+)%\)\s*" # Percentage
            r"CN:\d+\s+DL:(?P<speed>[\d\.]+[KMG]?i?B(?:/s)?)" # Speed with optional /s
            r"(?:\s+ETA:(?P<eta>[^\]]+))?" # Optional ETA
            r"\]" # Closing bracket
        )
        match = pattern.search(output)
        # --- END FIXED Regex ---

        if match:
            # Use .strip() on captured groups just in case of extra whitespace
            downloaded_bytes = match.group("downloaded").strip()
            total_size = match.group("total").strip()
            percentage = float(match.group("percent").strip())
            speed_raw = match.group("speed").strip() if match.group("speed") else None # Get raw speed value

            # Add '/s' if missing from captured speed for consistency in display
            if speed_raw and not speed_raw.endswith('/s'):
                speed_string = speed_raw + "/s"
            elif speed_raw:
                speed_string = speed_raw
            else:
                speed_string = "N/A" # Fallback if speed group somehow didn't match

            eta = match.group("eta").strip() if match.group("eta") else "N/A" # Excludes ']'
            log.debug(f"Regex matched: Speed='{speed_string}', ETA='{eta}'") # Log captured values
            Aria2c.link_info = True # Mark that we got info
        else:
            # Fallback attempt (should be very rare now)
            if "ETA:" in output and "%" in output and "/" in output:
                log.warning(f"Primary regex failed on line: '{output.strip()}' - Attempting fallback split.")
                # Fallback logic (remains the same)
                parts = output.split()
                try:
                    stats = next((p for p in parts if "/" in p and "%" in p), None)
                    if stats:
                         downloaded_bytes, rest = stats.split("/", 1)
                         if "(" in rest and ")" in rest:
                             total_size = rest.split("(")[0]
                             percent_str = rest.split("(")[1].split(")")[0]
                             percent_num_match = re.search(r"[\d\.]+", percent_str)
                             if percent_num_match:
                                  percentage = float(percent_num_match.group(0))
                             else: raise ValueError(f"Fallback: Could not extract number from percent_str '{percent_str}'")

                    eta_part = next((p for p in parts if p.startswith("ETA:")), None)
                    if eta_part:
                         eta_val = eta_part.split(":", 1)[1].strip()
                         eta = eta_val.removesuffix(']')
                    else: eta = "N/A"

                    speed_string = None # Mark for manual calculation
                    Aria2c.link_info = True

                except Exception as split_err:
                     log.warning(f"Fallback split parsing failed: {split_err} on line: '{output.strip()}'")
                     total_size = None; percentage = None; downloaded_bytes = None; eta = None
            else:
                 if output and "[#" in output:
                      log.debug(f"Line did not match regex or fallback criteria: {output.strip()}")


    except Exception as e:
        log.error(f"Could not parse output line: '{output.strip()}' - Error: {e}")
        total_size = None; percentage = None; downloaded_bytes = None; eta = None; speed_string = None


    # --- Status Update Section ---
    if percentage is not None and downloaded_bytes and total_size and eta:
        Messages.status_head = f"<b>📥 DOWNLOADING » </b>\n\n<b>🏷️ Name » </b><code>{current_filename}</code>\n"

        # Manual speed calculation only if regex somehow failed to capture speed
        if speed_string is None or speed_string == "N/A":
            log.debug("Calculating speed manually (fallback or regex failed speed group).")
            # ... (manual speed calc logic remains same) ...
            try:
                down_match = re.match(r"([\d\.]+)([KMG]?B)", downloaded_bytes)
                if down_match:
                     down_value = float(down_match.group(1))
                     down_unit = down_match.group(2)
                     multiplier = 1
                     if "G" in down_unit: multiplier = 1024**3
                     elif "M" in down_unit: multiplier = 1024**2
                     elif "K" in down_unit: multiplier = 1024
                     downloaded_numeric = down_value * multiplier
                     elapsed_time_seconds = (datetime.now() - BotTimes.task_start).total_seconds()
                     elapsed_time_seconds = max(1, elapsed_time_seconds)
                     current_speed = downloaded_numeric / elapsed_time_seconds
                     speed_string = f"{sizeUnit(current_speed)}/s"
                else: speed_string = "N/A"
            except Exception as speed_calc_err:
                log.error(f"Error calculating speed manually: {speed_calc_err}")
                speed_string = "N/A"

        if speed_string is None: speed_string = "N/A" # Final safety check

        try:
            clean_eta = eta.removesuffix(']') # Ensure trailing ']' is removed
            await status_bar(
                Messages.status_head, speed_string, int(percentage), clean_eta,
                downloaded_bytes, total_size, "Aria2c 🧨",
            )
        except Exception as status_err:
             log.error(f"Error calling status_bar: {status_err}")

    elif not Aria2c.link_info: # Timeout check
         elapsed_time_seconds = (datetime.now() - BotTimes.task_start).total_seconds()
         if elapsed_time_seconds >= 270:
             log.error(f"No valid progress info received for ~270s. Assuming dead link for: {current_filename}")

# ----- END OF FUNCTION -----
async def aria2_Download(link: str, num: int, pre_determined_name: str = None) -> bool:
    # Ensure necessary globals are accessible
    global BotTimes, Messages, TaskError, TRANSFER, Aria2c, Paths, log, clean_filename, apply_dot_style, on_output, is_google_drive, is_mega # Removed unnecessary urlparse, urllib, os here as they are imported

    success = False
    error_reason = "Aria2 Unknown Failure"
    exit_code = -1
    expected_filename = None
    raw_name = None

    # --- Determine Expected Filename (PRIORITIZE URL Path Robustly) ---
    url_derived_name = None
    try:
        # Attempt to get filename directly from the last part of the URL path
        # Use the imported module name explicitly
        parsed_url = urllib.parse.urlparse(link)
        url_path_name = os.path.basename(urllib.parse.unquote(parsed_url.path))
        if url_path_name:
            url_derived_name = url_path_name
            log.info(f"Derived raw name from URL path for link index {num}: '{url_derived_name}'")
        else:
            log.warning(f"URL path parsing resulted in empty filename for link index {num}.")
            # Fall through to check pre_determined_name
    except NameError as ne:
        # Catch NameError specifically related to missing imports
        log.error(f"IMPORT ERROR: Required module missing? {ne}. Cannot derive filename from URL.", exc_info=True)
        # Fall through to try pre_determined_name
    except Exception as url_parse_err:
        log.warning(f"Could not derive filename from URL path for link index {num}: {url_parse_err}. Checking pre_determined_name.")
        # Fall through to try pre_determined_name

    # Set raw_name based on priority: URL derived > pre_determined > fallback
    if url_derived_name:
        raw_name = url_derived_name
    elif pre_determined_name:
        raw_name = pre_determined_name
        log.info(f"Using pre-determined name for link index {num} as URL derivation failed/skipped: '{raw_name}'")
    else:
        log.warning(f"No filename derived from URL or pre-determined name for link {num}. Using fallback.")
        raw_name = f"aria2_download_{num}"

    # Clean the determined raw_name
    cleaned_name = clean_filename(raw_name)
    if not cleaned_name:
        log.warning(f"Raw name '{raw_name}' became invalid after cleaning for link index {num}. Using fallback.")
        cleaned_name = f"aria2_download_{num}_cleaned"

    expected_filename = cleaned_name
    display_name_for_status = cleaned_name
    # --- End Filename Determination ---

    log.info(f"Starting Aria2c download for link index {num} (Expecting: '{expected_filename}')")
    BotTimes.task_start = datetime.now()
    Messages.status_head = f"<b>📥 DOWNLOADING » </b><i>🔗Link {str(num).zfill(2)}</i>\n\n<b>🏷️ Name » </b><code>{display_name_for_status}</code>\n"

    try:
        os.makedirs(Paths.down_path, exist_ok=True)
    except OSError as mkdir_err:
        error_reason = f"Cannot create download dir: {mkdir_err}"
        log.error(error_reason)
        failed_info = {"link": link, "filename": expected_filename, "index": num, "reason": error_reason}
        if TaskError: TaskError.failed_links.append(failed_info)
        return False

    # --- Build command WITH --content-disposition=false ---
    command = [ "aria2c", "-x16", "--seed-time=0", "--summary-interval=1", "--max-tries=3",
                "--console-log-level=warn", "--file-allocation=none",
                "--content-disposition=false",
                "-d", Paths.down_path,
                link ]
    # --- End Command ---
    proc = None

    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        log.debug(f"Aria2c process started (PID: {proc.pid}) with command: {' '.join(command)}")

        # --- Async stream reader ---
        async def log_stream(stream, stream_name):
             while True:
                 line_bytes = await stream.readline()
                 if not line_bytes: break
                 line = line_bytes.decode('utf-8', errors='ignore').strip()
                 if line:
                     log.debug(f"Aria2c {stream_name}: {line}")
                     if stream_name == 'stdout':
                          await on_output(line, display_name_for_status)
                 await asyncio.sleep(0.05)

        stdout_task = asyncio.create_task(log_stream(proc.stdout, 'stdout'))
        stderr_task = asyncio.create_task(log_stream(proc.stderr, 'stderr'))

        exit_code = await proc.wait()
        await asyncio.gather(stdout_task, stderr_task)
        log.debug(f"Aria2c process finished with exit code: {exit_code}")

        # --- Success Check (with Added Diagnostics) ---
        await asyncio.sleep(0.2) # Small delay

        final_filepath_on_disk = os.path.join(Paths.down_path, expected_filename)
        file_exists = os.path.exists(final_filepath_on_disk)
        file_size = 0
        if file_exists:
             try: file_size = os.path.getsize(final_filepath_on_disk)
             except OSError as size_err: log.error(f"Could not get size for existing file {final_filepath_on_disk}: {size_err}")

        if exit_code == 0:
            if file_exists and file_size > 0:
                 log.info(f"Aria2c download complete. Found expected file: {final_filepath_on_disk} (Size: {file_size})")
                 success = True
            else:
                 log.error(f"Aria2 success code 0 but check failed for: {final_filepath_on_disk}")
                 log.warning(f"Details: File Exists? {file_exists}, File Size: {file_size}")
                 try:
                      dir_contents = os.listdir(Paths.down_path)
                      log.warning(f"Contents of download directory ({Paths.down_path}): {dir_contents}") # DIAGNOSTIC LOG
                 except Exception as list_err:
                      log.warning(f"Could not list download directory contents: {list_err}")
                 error_reason = f"Aria2 success code 0 but expected output file invalid/missing/empty: {expected_filename}"
                 success = False
                 if file_exists and file_size == 0:
                      log.warning(f"Removing empty file: {final_filepath_on_disk}")
                      try: os.remove(final_filepath_on_disk)
                      except OSError as cl_err: log.warning(f"Failed cleanup empty aria2 file: {cl_err}")
        else:
            # Handle failure codes
            if exit_code == 3: error_reason = "Aria2 Error: Resource Not Found (404?)"
            elif exit_code == 9: error_reason = "Aria2 Error: Not enough disk space"
            elif exit_code == 24: error_reason = "Aria2 Error: HTTP authorization failed (401/403?)"
            elif exit_code == 29: error_reason = "Aria2 Error: Network/Connection Issue (Code 29)"
            else: error_reason = f"Aria2 failed code {exit_code}"
            log.error(f"Aria2c download failed for link index {num}. Reason: {error_reason}")
            success = False
            # Cleanup
            if os.path.exists(final_filepath_on_disk):
                 try: os.remove(final_filepath_on_disk)
                 except OSError as cl_err: log.warning(f"Failed cleanup aria2 file: {cl_err}")

    except Exception as e:
        # Handle general exceptions
        error_reason = f"Aria2 Process Error: {str(e)[:100]}"
        log.error(f"Error running Aria2c process for link index {num}: {e}", exc_info=True)
        if proc and proc.returncode is None:
            try: proc.kill(); await proc.wait()
            except Exception as kill_err: log.warning(f"Error killing aria2c process: {kill_err}")
        success = False
        # Cleanup
        if expected_filename:
             cleanup_path = os.path.join(Paths.down_path, expected_filename)
             if os.path.exists(cleanup_path):
                 try: os.remove(cleanup_path)
                 except OSError as cl_err: log.warning(f"Failed cleanup aria2 file after exception: {cl_err}")

    # Report status using the filename derived from URL
    if success and expected_filename:
        try:
            dl_size = file_size if file_size > 0 else os.path.getsize(final_filepath_on_disk)
            TRANSFER.down_bytes.append(dl_size)
            TRANSFER.successful_downloads.append({'url': link, 'filename': expected_filename})
        except Exception as report_err: log.error(f"Error getting size/reporting success for {expected_filename}: {report_err}")
    elif not success:
        failed_info = {"link": link, "filename": expected_filename or raw_name, "index": num, "reason": error_reason}
        if TaskError: TaskError.failed_links.append(failed_info)

    return success
# ----- END OF FINAL FINAL REVISED FUNCTION -----
