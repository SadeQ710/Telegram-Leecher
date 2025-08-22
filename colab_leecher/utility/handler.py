# /content/Telegram-Leecher/colab_leecher/utility/handler.py
import os
import re
import shutil
import logging
import pathlib
import asyncio 
from time import time
from .. import OWNER, colab_bot, DUMP_ID 
from natsort import natsorted
from datetime import datetime
from os import makedirs, path as ospath
from ..uploader.telegram import upload_file
from .variables import BOT, MSG, BotTimes, Messages, Paths, TRANSFER, TaskError
from .converters import archive, extract, videoConverter, sizeChecker
from .helper import fileType, getSize, getTime, keyboard, shortFileName, sizeUnit, sysINFO
from pyrogram.errors import MessageNotModified
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

log = logging.getLogger(__name__)

async def Leech(path: str, remove_source: bool):
    global log, BOT, Paths, Messages, TaskError, TRANSFER, MSG 

    if not ospath.exists(path):
        log.error(f"Leech Error: Source path does not exist: {path}")
        TaskError.state = True; TaskError.text = "Leech source path missing."
        return

    log.info(f"Leech: Handler started for path: {path}")
    files_processed_count = 0
    files_failed_count = 0

    items_to_process = []
    if ospath.isdir(path):
         items_to_process = [ospath.join(path, item) for item in natsorted(os.listdir(path))]
    elif ospath.isfile(path):
         items_to_process = [path]
    else:
         log.error(f"Leech Error: Source path is neither file nor directory: {path}")
         TaskError.state = True; TaskError.text = "Leech source path invalid type."
         return

    total_items_to_process = len(items_to_process)
    log.info(f"Leech: Found {total_items_to_process} potential item(s) to process/upload from initial path: {path}")

    for index, item_path in enumerate(items_to_process):
        current_item_name = ospath.basename(item_path)
        log.info(f"Leech: Processing item {index + 1}/{total_items_to_process}: {current_item_name}")

        if TaskError.state:
            log.warning(f"Leech: Skipping item '{current_item_name}' due to prior error state.")
            files_failed_count += 1
            continue 

        upload_path_for_item = item_path 
        processing_required_and_done = False 


        try: 
            processing_required_and_done = await sizeChecker(upload_path_for_item, remove_source) 

            if TaskError.state:
                 log.error(f"Leech: Error during sizeChecker/processing for '{current_item_name}'. Reason: {TaskError.text}")
                 raise Exception(TaskError.text) 


            upload_source_location = upload_path_for_item             
            if processing_required_and_done:
                potential_processed_path = Paths.temp_zpath 
                log.info(f"Leech: Processing was required for '{current_item_name}'. Checking for output in {potential_processed_path}")
                if ospath.exists(potential_processed_path) and os.listdir(potential_processed_path):
                    upload_source_location = potential_processed_path
                    log.info(f"Leech: Found processed content. Uploading content from: {upload_source_location}")
                else:
                    log.warning(f"Leech: Processing done but processed path '{potential_processed_path}' missing or empty. Uploading original item from: {upload_source_location}")
            else:
                log.info(f"Leech: No processing needed for '{current_item_name}'. Uploading from: {upload_source_location}")

            # --- Uploading ---
            if not ospath.exists(upload_source_location):
                 log.error(f"Leech: Final upload source location '{upload_source_location}' does not exist. Skipping upload for '{current_item_name}'.")
                 if not TaskError.state: TaskError.state = True; TaskError.text = f"Upload source missing: {ospath.basename(upload_source_location)}"
                 raise Exception(TaskError.text) 

            upload_success = False
            if ospath.isdir(upload_source_location):
                log.info(f"Leech: Uploading contents of directory: {upload_source_location} for original item '{current_item_name}'")
                files_in_dir = [f for f in natsorted(os.listdir(upload_source_location)) if ospath.isfile(ospath.join(upload_source_location, f))]
                
                if not files_in_dir:
                     log.warning(f"Leech: Upload directory '{upload_source_location}' contains no files to upload for item '{current_item_name}'.")
                     upload_success = True # Treat empty processed dir as success for this item
                else:
                     total_files_in_dir = len(files_in_dir)
                     log.info(f"Leech: Found {total_files_in_dir} file(s) in '{upload_source_location}' to upload for item '{current_item_name}'.")
                     all_parts_uploaded = True
                     for file_index, sub_item_name in enumerate(files_in_dir): 
                         sub_item_path = ospath.join(upload_source_location, sub_item_name)
                         part_display_name = f"{current_item_name}.part{str(file_index + 1).zfill(3)}"
                         log.info(f"Leech: Uploading file from directory: {sub_item_name} (Display: {part_display_name})")
                         uploaded = await upload_file(sub_item_path, part_display_name) # Ensure upload_file is imported

                         if uploaded is not True:
                              log.error(f"Leech: upload_file returned failure for sub-item: {sub_item_name} (Display: {part_display_name})")
                              all_parts_uploaded = False
                              if TaskError and not TaskError.state:
                                   TaskError.state = True
                                   TaskError.text = TaskError.text or f"Upload failed for {part_display_name}"
                              break 
                     
                     upload_success = all_parts_uploaded
                     if not all_parts_uploaded:
                         log.error(f"Leech: Not all files in directory '{upload_source_location}' were uploaded successfully for item '{current_item_name}'.")

            elif ospath.isfile(upload_source_location):
                log.info(f"Leech: Uploading single file: {upload_source_location} (Display: {current_item_name})")
                uploaded = await upload_file(upload_source_location, current_item_name) # Ensure upload_file is imported
                if uploaded is True: 
                    upload_success = True
                else: 
                    log.error(f"Leech: upload_file returned failure for single file: {current_item_name}")
                    upload_success = False
                    if TaskError and not TaskError.state:
                         TaskError.state = True
                         TaskError.text = TaskError.text or f"Upload failed for {current_item_name}"
            else: 
                log.error(f"Leech: Path '{upload_source_location}' is not a file or directory. Skipping.")
                if not TaskError.state: TaskError.state = True; TaskError.text = f"Invalid upload source type: {upload_source_location}"
                raise Exception(TaskError.text) 

            # --- Update Counts ---
            if upload_success:
                 files_processed_count += 1
                 log.info(f"Leech: Successfully processed/uploaded item corresponding to: {current_item_name}")
            else:
                 # Failure reason should already be logged and TaskError potentially set
                 log.error(f"Leech: Failed to process/upload item corresponding to: {current_item_name}")
                 # We will increment files_failed_count in the except block
                 raise Exception(TaskError.text or f"Upload failed for {current_item_name}") # Ensure an exception is raised if upload failed

            # --- Cleanup Temporary Directory AFTER Upload (if processing occurred) ---
            if processing_required_and_done and upload_source_location == Paths.temp_zpath and ospath.exists(Paths.temp_zpath):
                 log.info(f"Cleaning up temporary processing directory: {Paths.temp_zpath}")
                 shutil.rmtree(Paths.temp_zpath, ignore_errors=True)
                 try: makedirs(Paths.temp_zpath, exist_ok=True) 
                 except Exception as mkdir_err: log.warning(f"Could not recreate temp dir {Paths.temp_zpath}: {mkdir_err}")
        
        # --- !!! THIS IS THE RESTORED except BLOCK !!! ---
        # It catches errors specific to the processing of the current item_path
        except Exception as item_err:
            files_failed_count += 1 # Increment failure count here
            log.error(f"Leech: Error processing item '{current_item_name}': {item_err}", exc_info=True)
            # Ensure TaskError state is set if not already
            if not TaskError.state: 
                TaskError.state = True
                # Use the specific error message if TaskError.text wasn't set by the failing function
                TaskError.text = TaskError.text or f"Error processing {current_item_name}: {str(item_err)[:100]}"
            # The loop will continue to the next item unless TaskError.state causes skipping at the top

        # --- End of Try block for individual item processing ---

    # --- End of for loop ---

    log.info(f"Leech: Function finished. Processed: {files_processed_count}, Failed: {files_failed_count}")
    # No return needed, Do_Leech checks TaskError state


    # Let Do_Leech check the final TaskError state
async def Zip_Handler(down_path: str, is_split: bool, remove: bool):
    # (Include full, corrected Zip_Handler body here)
    global BOT, Messages, MSG, TRANSFER, BotTimes, Paths, TaskError
    log.info(f"Zip Handler started for: {down_path}")
    # Add full implementation based on previous versions, ensuring TaskError is set on failure
    pass # Replace with full implementation

# Replace Unzip_Handler in colab_leecher/utility/handler.py
# Ensure necessary imports: os, shutil, log, Paths, TaskError, Extractor, natsorted, Messages, BOT

# ----- REPLACE the existing Unzip_Handler function in handler.py with this: -----
async def Unzip_Handler(source_path: str, pswd: str | None = None):
    """
    Handles extraction of archives found within the source_path.
    Improved to correctly handle multi-part RAR archives.
    """
    global log, BOT, Paths, Messages, BotTimes, MSG, TaskError, TRANSFER, cleanup_paths # Ensure all needed globals
    from .converters import extract # Ensure 'extract' is imported

    log.info(f"Unzip Handler started for: {source_path}")
    if not ospath.isdir(source_path):
        log.error(f"Unzip Handler Error: Source path is not a directory: {source_path}")
        TaskError.state = True
        TaskError.text = f"Unzip source path invalid: {ospath.basename(source_path)}"
        return False # Cannot proceed

    target_unzip_path = Paths.temp_unzip_path # Get target path from variables
    os.makedirs(target_unzip_path, exist_ok=True) # Ensure target dir exists

    archive_files_found = []
    try:
        # List all files, ignore directories directly inside source_path
        items = [f for f in os.listdir(source_path) if ospath.isfile(ospath.join(source_path, f))]
        log.info(f"Scanning directory for archives: {source_path}. Found {len(items)} files.")

        # Identify potential archive files (common extensions)
        archive_extensions = {".rar", ".zip", ".7z", ".tar", ".gz", ".tgz", ".001", ".z01"}
        archive_files_found = [f for f in items if any(f.lower().endswith(ext) for ext in archive_extensions)]

        if not archive_files_found:
            log.warning(f"No archive files found in {source_path}. Skipping extraction.")
            return True # No archives to extract is not an error in itself

    except Exception as list_err:
        log.error(f"Error listing files in {source_path}: {list_err}", exc_info=True)
        TaskError.state = True
        TaskError.text = f"Error scanning unzip source: {str(list_err)[:50]}"
        return False

    extraction_errors = []
    processed_bases = set() # Keep track of processed multi-part archives

    for item_name in archive_files_found:
        item_path = ospath.join(source_path, item_name)
        base_name, ext_lower = ospath.splitext(item_name.lower())
        is_multipart_rar = False
        first_part_identifier = None

        # --- Logic to identify the *first* part of multi-part RAR ---
        rar_part_match = re.match(r"(.+)\.part(\d+)\.rar$", item_name.lower())
        if rar_part_match:
             base_name = rar_part_match.group(1)
             part_num = int(rar_part_match.group(2))
             is_multipart_rar = True
             if part_num == 1:
                 first_part_identifier = item_path # This is the .part1.rar file
             else:
                 # This is part 2 or later, skip extraction attempt
                 log.debug(f"Skipping extraction attempt for subsequent RAR part: {item_name}")
                 processed_bases.add(base_name) # Mark base as handled by part 1 later
                 continue
        elif ext_lower == ".rar":
            # Could be a single RAR or the first part without .partX naming
            # Check if other parts like .r00, .r01 exist? (More complex, skip for now)
            # Assume this is the first/only part if no .partX match was found earlier
            first_part_identifier = item_path
            base_name, _ = ospath.splitext(item_name) # Get base name without .rar
            # Avoid processing if a .part1.rar for this base was already processed
            if base_name in processed_bases:
                 log.debug(f"Skipping extraction for {item_name}, base '{base_name}' likely handled by .part1.rar")
                 continue
        # --- End Multi-part RAR Logic ---

        # For non-RAR or identified first RAR parts
        elif ext_lower in archive_extensions: # Handle zip, 7z, tar etc.
             first_part_identifier = item_path
             base_name, _ = ospath.splitext(item_name)
             # Add logic here if needed to detect first parts of zip/7z multipart, e.g. .001 / .z01
             if ext_lower == ".001" or ext_lower == ".z01":
                  log.debug(f"Identified potential first part of split archive: {item_name}")
             elif ext_lower in [".002", ".z02"]: # Example for subsequent parts
                  log.debug(f"Skipping subsequent split part: {item_name}")
                  continue # Skip explicit extraction of later parts

        # --- Extraction Attempt ---
        if first_part_identifier:
            log.info(f"Attempting extraction for: {ospath.basename(first_part_identifier)}")
            success = False
            try:
                # --- CORRECTED FUNCTION CALL: Use 'extract' ---
                # Pass only the path to the (first) archive file and remove=False
                # Password is handled inside 'extract' using BOT.Options.unzip_pswd
                success = await extract(first_part_identifier, remove=False)
                # --- End Corrected Call ---

                if success:
                    log.info(f"Extraction successful for base: {base_name}")
                    processed_bases.add(base_name) # Mark as done
                else:
                    # Extract function logs errors internally, but we add context here
                    log.error(f"Extraction failed for '{item_name}'. Reason logged by 'extract' function.")
                    # Use TaskError.text set by extract function if available? Or set generic one?
                    fail_reason = TaskError.text if TaskError.state else "Unknown (from extract)"
                    extraction_errors.append(f"Failed: {item_name} - {fail_reason}")
                    TaskError.state = False # Reset TaskError state after logging it for this file

            except Exception as extract_call_err:
                # Catch errors calling the extract function itself
                log.error(f"Unexpected error calling extract for {item_name}: {extract_call_err}", exc_info=True)
                extraction_errors.append(f"Failed: {item_name} - Call Error: {str(extract_call_err)[:50]}")

    # --- Final Status Check ---
    if extraction_errors:
        log.error(f"Unzip_Handler finished, but {len(extraction_errors)} extraction error(s) occurred.")
        # Combine errors for TaskError
        TaskError.state = True
        TaskError.text = "; ".join(extraction_errors)
        # Decide if the whole task fails or continues with successfully extracted files
        # For now, let's return False indicating the handler had issues
        return False
    else:
        log.info("Unzip_Handler finished successfully. All archives processed.")
        return True # Indicate overall success

# ----- END OF REPLACEMENT BLOCK -----

async def cancelTask(Reason: str):
    global BOT, BotTimes, Messages, MSG, TaskError, TRANSFER, Paths, OWNER, colab_bot, log # Ensure log is accessible

    task_failed = TaskError.state # Check if task failed before cancel was called
    final_reason = TaskError.text if task_failed and TaskError.text else Reason # Use specific error reason if task failed
    log.warning(f"Task cancellation/completion triggered. Final Reason: {final_reason}")

    # --- Generate Report String ---
    try: time_spent = getTime((datetime.now() - BotTimes.start_time).seconds)
    except Exception: time_spent = "Unknown"

    report_content = f"===== Task Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====\n"
    report_content += f"Reason for Stop/Completion: {final_reason}\n"
    report_content += f"Mode: {BOT.Mode.mode or 'N/A'}, Type: {BOT.Mode.type or 'N/A'}, Service: {BOT.Options.service_type or 'N/A'}\n"
    report_content += f"Total Time Elapsed: {time_spent}\n"
    report_content += f"Source Link: {Messages.src_link or 'N/A'}\n\n"

    processed_urls = set() # Use a set for efficient lookup

    # Successful Downloads
    report_content += f"--- Successful Downloads ({len(TRANSFER.successful_downloads)}) ---\n"
    if TRANSFER.successful_downloads:
        for idx, item in enumerate(TRANSFER.successful_downloads):
            url = item.get('url', 'N/A')
            processed_urls.add(url) # Add URL to processed set
            report_content += f"{idx+1}. Filename: {item.get('filename', 'N/A')}\n"
            report_content += f"   URL: {url}\n\n"
    else: report_content += "   None\n\n"

    # Failed Downloads
    report_content += f"--- Failed Downloads ({len(TaskError.failed_links)}) ---\n"
    if TaskError.failed_links:
        for idx, item in enumerate(TaskError.failed_links):
            url = item.get('link', 'N/A')
            processed_urls.add(url) # Add URL to processed set
            report_content += f"{idx+1}. Index/Link Num: {item.get('index', 'N/A')}\n"
            report_content += f"   Filename: {item.get('filename', 'N/A')}\n"
            report_content += f"   URL: {url}\n"
            report_content += f"   Reason: {item.get('reason', 'Unknown')}\n\n"
    else: report_content += "   None\n\n"

    # --- Skipped / Not Attempted Links ---
    skipped_links = []
    original_links = BOT.SOURCE if BOT.SOURCE else []
    original_filenames = BOT.Options.filenames if BOT.Options.filenames else []
    if len(original_links) > (len(TRANSFER.successful_downloads) + len(TaskError.failed_links)):
        for i, url in enumerate(original_links):
            if url not in processed_urls:
                # Find corresponding filename using index, handle potential length mismatch
                filename = original_filenames[i] if i < len(original_filenames) else "N/A (Filename List Mismatch?)"
                skipped_links.append({'url': url, 'filename': filename})

    report_content += f"--- Skipped / Not Attempted ({len(skipped_links)}) ---\n"
    if skipped_links:
        for idx, item in enumerate(skipped_links):
             report_content += f"{idx+1}. Filename: {item.get('filename', 'N/A')}\n"
             report_content += f"   URL: {item.get('url', 'N/A')}\n\n"
    else: report_content += "   None\n\n"
    # --- End Skipped Links ---


    # Successful Uploads (Leech Mode Only)
    if BOT.Mode.mode != "mirror":
        report_content += f"--- Successful Uploads ({len(TRANSFER.sent_file)}) ---\n"
        # ... (rest of upload reporting logic remains the same) ...
        if not TRANSFER.sent_file: report_content += "   None\n\n"

    report_content += "===== End of Report =====\n"
    # --- End Report String Generation ---

    # --- Save Report File ---
    report_file_path = os.path.join(Paths.WORK_PATH, "download_report.txt")
    report_saved = False
    try:
        os.makedirs(Paths.WORK_PATH, exist_ok=True)
        with open(report_file_path, "w", encoding="utf-8") as f: f.write(report_content)
        log.info(f"Download report saved to {report_file_path}")
        report_saved = True
    except Exception as e: log.error(f"Failed to save download report file: {e}"); report_file_path = None
    # --- End Save Report File ---

    # --- Cancel Async Task ---
    if BOT.State.task_going and BOT.TASK:
        try:
            if not BOT.TASK.done(): BOT.TASK.cancel(); await asyncio.sleep(1); log.info("Ongoing asyncio task cancelled.")
        except asyncio.CancelledError: log.info("Asyncio task was already cancelled.")
        except Exception as e: log.error(f"Error during task cancellation itself: {e}", exc_info=True)
    # --- End Cancel Async Task ---

    # --- Conditional Workspace Cleanup ---
    skip_cleanup = bool(TaskError.failed_links) # Skip if any download failed
    if not skip_cleanup:
        try:
             if os.path.exists(Paths.WORK_PATH): shutil.rmtree(Paths.WORK_PATH, ignore_errors=True); log.info(f"Cleaning up workspace: {Paths.WORK_PATH}")
        except Exception as e: log.error(f"Error during workspace cleanup: {e}", exc_info=True)
    else:
         log.warning(f"Workspace cleanup skipped due to download failures. Check {Paths.WORK_PATH} for partial downloads and report.")
    # --- End Conditional Cleanup ---

    # --- Reset States ---
    BOT.State.task_going = False
    BOT.State.started = False
    BOT.TASK = None
    # --- End Reset States ---

    # --- Prepare Final Telegram Message ---
    if task_failed: final_summary_header = f"❌ **Task Failed!**"
    else: final_summary_header = f"🛑 **Task Cancelled by User**" # Or Completed if no failure reason

    final_summary_text = f"{final_summary_header}\n"
    final_summary_text += f"Reason: {final_reason}\n"
    final_summary_text += f"Elapsed: {time_spent}\n"
    if report_saved: final_summary_text += "\n📜 Report file generated & sent."
    else: final_summary_text += "\n⚠️ Report file generation failed."

    # --- Add FAILED & SKIPPED Counts to Telegram Message ---
    if TaskError.failed_links:
        final_summary_text += f"\nFailed Downloads: {len(TaskError.failed_links)}"
    if skipped_links: # Use the list generated earlier
        final_summary_text += f"\nSkipped/Not Attempted: {len(skipped_links)}"
    if TaskError.failed_links or skipped_links:
         final_summary_text += "\n(See report file for details)"
    # --- END Add Counts ---

    # --- Send Report and Final Message ---
    report_message_id_to_reply = None
    if OWNER and colab_bot:
        try:
             # 1. Send report file if saved
             if report_saved and os.path.exists(report_file_path):
                  log.info(f"Sending report file {report_file_path} to owner {OWNER}")
                  report_msg = await colab_bot.send_document( OWNER, document=report_file_path, caption=f"Download Report: {BOT.Mode.mode} - {final_reason}"[:200] )
                  report_message_id_to_reply = report_msg.id
                  try: os.remove(report_file_path)
                  except OSError as e: log.warning(f"Could not remove report file {report_file_path}: {e}")
             else: log.warning("Report file not saved or found, cannot send document.")

             # 2. Send final summary message
             final_markup = InlineKeyboardMarkup([[InlineKeyboardButton("Channel 📣", url="https://t.me/Colab_Leecher"), InlineKeyboardButton("Group 💬", url="https://t.me/Colab_Leecher_Discuss")]])
             if report_message_id_to_reply:
                 await colab_bot.send_message(OWNER, final_summary_text, reply_to_message_id=report_message_id_to_reply, reply_markup=final_markup, disable_web_page_preview=True)
             elif MSG.status_msg: # Fallback: Reply to original status message
                 try: await MSG.status_msg.reply_text(final_summary_text, quote=True, reply_markup=final_markup, disable_web_page_preview=True)
                 except Exception: await colab_bot.send_message(OWNER, final_summary_text, reply_markup=final_markup, disable_web_page_preview=True)
             else: # Fallback: Send new message
                  await colab_bot.send_message(OWNER, final_summary_text, reply_markup=final_markup, disable_web_page_preview=True)
             log.info("Sent final cancellation/failure message to owner.")

        except Exception as send_err: log.error(f"Failed send cancellation report/summary message: {send_err}")

    # Delete original status message *last*, if it exists
    if MSG.status_msg:
        try: await MSG.status_msg.delete()
        except Exception as del_err: log.warning(f"Could not delete original status message: {del_err}")
        finally: MSG.status_msg = None
    # --- End Send Report and Final Message ---

# --- End of cancelTask function ---

async def SendLogs(is_leech: bool):
    # (Include full, corrected SendLogs body here)
    global TRANSFER, Messages, BOT, BotTimes, MSG, OWNER, colab_bot
    log.info("SendLogs: Preparing final summary...")
    # Add full implementation based on previous versions
    pass # Replace with full implementation

   
# --- Zip_Handler (ensure logging and error handling if needed) ---
async def Zip_Handler(down_path: str, is_split: bool, remove: bool):
    # Function body correctly indented
    # Needs to ideally set TaskError.state=True on failure
    global BOT, Messages, MSG, TRANSFER, BotTimes, Paths, TaskError
    log.info(f"Zip Handler started for: {down_path}")
    try:
         await archive(down_path, is_split, remove) # Assume archive handles detailed logging/errors
         # Check if archive function set TaskError
         if TaskError and TaskError.state:
              log.error(f"Zip Handler failed because archive function reported an error.")
              return # Propagate failure
         # Check if output exists as basic validation
         archive_name = Messages.download_name # Get name set by archive
         archive_path = ospath.join(Paths.temp_zpath, archive_name)
         if not ospath.exists(Paths.temp_zpath) or not os.listdir(Paths.temp_zpath):
              log.error("Zipping failed, output directory empty/missing.")
              if TaskError: TaskError.state = True; TaskError.text = "Zipping failed (no output)"
              return
         TRANSFER.total_down_size = getSize(Paths.temp_zpath)
         log.info(f"Zipping complete. Output size: {sizeUnit(TRANSFER.total_down_size)}")
    except Exception as zip_err:
         log.error(f"Error in Zip_Handler: {zip_err}", exc_info=True)
         if TaskError: TaskError.state = True; TaskError.text = f"Zip Handler Error: {zip_err}"



    # Messages.status_head = f"\n<b>📂 EXTRACTING » </b>\n\n<code>{os.path.basename(down_path)}</code>\n"
    # if MSG.status_msg: await MSG.status_msg.edit_text(...) # Status handled inside extract now

    extracted_something = False
    temp_unzip_path = Paths.temp_unzip_path # Defined in variables
    supported_exts = [".7z", ".gz", ".zip", ".rar", ".tar", ".tgz", ".001", ".z01"] # Example list

    try:
         if ospath.isfile(down_path):
              # If it's a single file, check if it's an archive
              filename = ospath.basename(down_path).lower()
              _, ext = ospath.splitext(filename)
              if ext in supported_exts:
                   log.info(f"Attempting extract single file: {filename}")
                   # Assume extract returns success/fail status or sets TaskError
                   extract_success = await extract(down_path, remove) # Pass remove flag
                   if extract_success: extracted_something = True
                   else: TaskError.state = True # Ensure state is set if extract fails silently
              else:
                   log.warning(f"Single file '{filename}' is not a supported archive type for extraction.")
                   # Copy the single non-archive file to the unzip path for consistency
                   makedirs(temp_unzip_path, exist_ok=True)
                   shutil.copy2(down_path, temp_unzip_path)
                   Messages.download_name = ospath.basename(down_path) # Set name context
                   if remove: os.remove(down_path) # Remove original if requested
                   extracted_something = True # Mark as 'processed' by copying
         elif ospath.isdir(down_path):
              # If it's a directory, try extracting supported archives within it
              log.info(f"Scanning directory for archives: {down_path}")
              any_extracted_in_dir = False
              files_in_dir = [str(p) for p in pathlib.Path(down_path).rglob("*") if p.is_file()]
              for f_path in natsorted(files_in_dir):
                   filename = ospath.basename(f_path).lower()
                   _, ext = ospath.splitext(filename)
                   if ext in supported_exts:
                        log.info(f"Attempting extract archive within dir: {filename}")
                        extract_success = await extract(f_path, remove) # Pass remove flag
                        if extract_success: any_extracted_in_dir = True; extracted_something = True
                        else: TaskError.state = True; break # Stop if any extraction fails? Or continue? Let's stop.
              if TaskError.state: return # Exit if extraction failed mid-directory

              # If no archives were found/extracted in directory, copy original content
              if not any_extracted_in_dir:
                   log.warning(f"No supported archives found/extracted in directory: {down_path}. Copying original content.")
                   try:
                        # Copy contents into the temp_unzip_path
                        makedirs(temp_unzip_path, exist_ok=True)
                        shutil.copytree(down_path, temp_unzip_path, dirs_exist_ok=True)
                        if remove: shutil.rmtree(down_path) # Remove original dir if requested
                        Messages.download_name = ospath.basename(down_path) # Set name context
                        extracted_something = True # Mark as 'processed'
                   except Exception as copy_err:
                        log.error(f"Failed copy original dir content: {copy_err}")
                        if TaskError: TaskError.state = True; TaskError.text = f"Copy error: {copy_err}"
                        return
         else:
              # Should not happen if path check at start works
              log.error(f"Unzip source path is neither file nor directory: {down_path}")
              if TaskError: TaskError.state = True; TaskError.text = "Invalid unzip source"
              return

         # Final check and size calculation
         if ospath.exists(temp_unzip_path):
              TRANSFER.total_down_size = getSize(temp_unzip_path)
              log.info(f"Extraction/Copy complete. Final size in '{temp_unzip_path}': {sizeUnit(TRANSFER.total_down_size)}")
         elif not TaskError.state:
              # If no error state was set, but output path is missing, set error
              log.error(f"Extraction failed, output path missing: {temp_unzip_path}")
              TaskError.state = True; TaskError.text = "Extraction failed (no output)"

    except Exception as unzip_err:
         log.error(f"Error in Unzip_Handler: {unzip_err}", exc_info=True)
         if TaskError: TaskError.state = True; TaskError.text = f"Unzip Handler Error: {unzip_err}"



# --- SendLogs Function (Ensure it exists and is correct) ---
async def SendLogs(is_leech: bool):
    # Function body correctly indented
    global TRANSFER, Messages, BOT, BotTimes, MSG, OWNER, colab_bot # Ensure necessary globals
    log.info("SendLogs: Preparing final summary...")
    try:
         total_uploaded_size = sum(TRANSFER.up_bytes) # Use instance
         file_count = len(TRANSFER.sent_file) # Use instance for count
         file_count_str = f"<code>{file_count}</code>"

         final_text = f"<b>☘️ Files Sent:</b> {file_count_str}\n\n<b>📜 Logs:</b>\n";
         l_ink = "⌬─────[「 Colab Usage 」](https://colab.research.google.com/drive/12hdEqaidRZ8krqj7rpnyDzg1dkKmvdvp)─────⌬" # Example link

         if is_leech:
             file_count_display = f"├<b>☘️ File Count » </b>{file_count_str} Files\n"
             size_label = "Uploaded"
             size_value = sizeUnit(total_uploaded_size)
         else: # Mirror mode
             file_count_display = ""
             size_label = "Total Size"
             size_value = sizeUnit(TRANSFER.total_down_size) # Use instance for total size

         # Determine display name safely
         display_name = BOT.Options.custom_name if BOT.Options.custom_name else Messages.download_name if Messages.download_name else "N/A"
         # Calculate elapsed time safely
         try: elapsed_seconds = (datetime.now() - BotTimes.start_time).seconds; elapsed_time_str = getTime(elapsed_seconds)
         except Exception: elapsed_time_str = "N/A"

         last_text = (f"\n\n<b>#{(BOT.Mode.mode).upper()}_COMPLETE 🔥</b>\n\n"
                      f"╭<b>📛 Name » </b><code>{display_name}</code>\n"
                      f"├<b>📦 {size_label} » </b><code>{size_value}</code>\n"
                      f"{file_count_display}"
                      f"╰<b>⏱️ Time Taken »</b> <code>{elapsed_time_str}</code>")

         if MSG.status_msg:
             final_status_text = Messages.task_msg + l_ink + last_text
             final_markup = InlineKeyboardMarkup([
                  [InlineKeyboardButton("Git Repo 🪲", url="https://github.com/XronTrix10/Telegram-Leecher")],
                  [InlineKeyboardButton("Channel 📣", url="https://t.me/Colab_Leecher"), InlineKeyboardButton("Group 💬", url="https://t.me/Colab_Leecher_Discuss")]
             ])
             try:
                 # Send summary to dump chat first (replying to last sent file there)
                 if MSG.sent_msg:
                     await MSG.sent_msg.reply_text(text=f"**SOURCE »** __[Here]({Messages.src_link})__" + last_text, disable_web_page_preview=True)
                     log.info("Sent final summary to dump chat.")
                 else:
                     log.warning("Cannot send final summary to dump chat, MSG.sent_msg invalid.")

                 # Edit the status message in owner chat
                 await MSG.status_msg.edit_text(text=final_status_text, reply_markup=final_markup, disable_web_page_preview=True)
                 log.info("Edited final status message for owner.")

                 # Send detailed file log if leeching and files were sent
                 if is_leech and file_count > 0:
                     log_texts = []; current_log_text = f"<b>📜 Uploaded Files Log ({file_count}):</b>\n"
                     for i in range(file_count):
                          try:
                              file_obj = TRANSFER.sent_file[i]
                              fileName = TRANSFER.sent_file_names[i] if i < len(TRANSFER.sent_file_names) else "Unknown Name"
                              link_chat_id = str(file_obj.chat.id).replace("-100", "") if hasattr(file_obj, 'chat') and hasattr(file_obj.chat, 'id') else None
                              msg_id = file_obj.id if hasattr(file_obj, 'id') else None
                              file_link = f"https://t.me/c/{link_chat_id}/{msg_id}" if link_chat_id and msg_id else "N/A"
                              fileText = f"\n({str(i+1).zfill(2)}) <a href='{file_link}'>{fileName}</a>" if file_link != "N/A" else f"\n({str(i+1).zfill(2)}) {fileName} (Link Unavailable)"

                              if len(current_log_text + fileText) >= 4096:
                                   log_texts.append(current_log_text); current_log_text = fileText
                              else: current_log_text += fileText
                          except Exception as log_build_err:
                              log.error(f"Error building log entry {i+1}: {log_build_err}"); current_log_text += f"\n({str(i+1).zfill(2)}) Error."
                     log_texts.append(current_log_text) # Add final part

                     # Send log parts, replying to the status message
                     last_log_msg = MSG.status_msg
                     for fn_txt in log_texts:
                          try:
                               last_log_msg = await last_log_msg.reply_text(text=fn_txt, disable_web_page_preview=True, quote=True)
                               await asyncio.sleep(0.5) # Use asyncio.sleep
                          except Exception as e:
                               log.error(f"Error Sending log part: {e}", exc_info=False)
                               # Send remaining parts as new messages if reply fails?
                               if OWNER and colab_bot: await colab_bot.send_message(OWNER, fn_txt)
                               break # Stop trying to reply if it fails once
             except Exception as e:
                 log.error(f"Error sending/editing final logs: {e}", exc_info=True)
                 if OWNER and colab_bot: await colab_bot.send_message(OWNER, f"Error updating final status: {e}")
         else:
             log.error("Cannot send final logs: Status message object missing.")
             # Send basic summary directly to owner if status msg is lost
             if OWNER and colab_bot: await colab_bot.send_message(OWNER, last_text)

    except Exception as send_log_err:
         log.error(f"Error in SendLogs function: {send_log_err}", exc_info=True)

    finally:
         # Reset states after logging attempt (success or fail)
         BOT.State.started = False; BOT.State.task_going = False; BOT.State.prefix = False
         BOT.State.suffix = False; BOT.State.expecting_nzb_filenames = False
         BOT.State.expecting_delta_filenames = False; BOT.State.expecting_bitso_filenames = False
         BOT.Options.filenames = []
         log.info("Bot states reset after task completion/logging.")
