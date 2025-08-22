#================================================
#FILE: colab_leecher/downlader/mega.py
#================================================
#Telegra-Leecher/colab_leecher/downlader/mega.py
import subprocess
import logging 
from datetime import datetime
from colab_leecher.utility.helper import status_bar, getTime
from colab_leecher.utility.variables import BotTimes, Messages, Paths, TaskError, TRANSFER 
from pymegatools import Megatools, MegaError
import os 

log = logging.getLogger(__name__) 



async def megadl(link: str, num: int) -> bool: 
    global BotTimes, Messages, Paths, TaskError, log, TRANSFER 

    intended_filename = "Unknown Mega File" 

    log.info(f"Starting Mega download for link index {num}") 
    BotTimes.task_start = datetime.now()
    mega = Megatools()
    success = False
    try:

        Messages.download_name = ""
        await mega.async_download(link, progress=pro_for_mega, path=Paths.down_path)

        intended_filename = Messages.download_name or intended_filename 

        final_filename = Messages.download_name or "Unknown Mega Download" 
        if not final_filename.startswith("Unknown"):
            
             if os.path.exists(os.path.join(Paths.down_path, final_filename)):
                  TRANSFER.successful_downloads.append({'url': link, 'filename': final_filename})
                  success = True
             else:
                  log.error(f"Mega download finished for {link} but output file '{final_filename}' not found.")
                  failed_info = {"link": link, "filename": final_filename, "index": num, "reason": "Output file not found post-download"}
                  if TaskError: TaskError.failed_links.append(failed_info)
                  success = False
        else:
             log.warning(f"Mega download finished for link {num}, but filename is unknown. Cannot confirm success.")
             # Assume failure if we don't know the filename? Or success? Let's assume failure.
             failed_info = {"link": link, "filename": "Unknown", "index": num, "reason": "Could not determine filename"}
             if TaskError: TaskError.failed_links.append(failed_info)
             success = False

    except MegaError as e:
        error_reason = f"MegaError: {e}"
        log.error(f"An Error occurred during Mega download for link {num}: {error_reason}")

        failed_info = {"link": link, "filename": intended_filename, "index": num, "reason": error_reason}
        if TaskError: TaskError.failed_links.append(failed_info)
        success = False
    except Exception as e:
        error_reason = f"Unexpected Mega Error: {str(e)[:100]}"
        log.error(f"Unexpected error during Mega download {link}: {e}", exc_info=True)
  
        failed_info = {"link": link, "filename": intended_filename, "index": num, "reason": error_reason}
        if TaskError: TaskError.failed_links.append(failed_info)
        success = False

    return success

async def pro_for_mega(stream, process):
    line = stream[-1]
    file_name = "N/A"
    percentage = 0
    downloaded_size = "N/A"
    total_size = "N/A"
    speed = "N/A"
    eta = "Unknown"  
    try:
        ok = line.split(":")
        file_name = ok[0]
        ok = ok[1].split()
        percentage = float(ok[0][:-1])
        downloaded_size = ok[2] + " " + ok[3]
        total_size = ok[7] + " " + ok[8]
        speed = ok[9][1:] + " " + ok[10][:-1]

        
        remaining_bytes = float(ok[7]) - float(ok[2])
        bytes_per_second = float(ok[9][1:]) * (1024 if ok[10][-1] == 'K' else 1)  # Convert KB/s to bytes/s if necessary
        if bytes_per_second != 0:
            remaining_seconds = remaining_bytes / bytes_per_second
            eta = getTime(remaining_seconds)

    except Exception:
        pass

    Messages.download_name = file_name
    Messages.status_head = f"<b>📥 DOWNLOADING FROM MEGA » </b>\n\n<b>🏷️ Name » </b><code>{file_name}</code>\n"

    await status_bar(
        Messages.status_head,
        speed,
        percentage,
        eta,
        downloaded_size,
        total_size,
        "Mega",
    )
