import logging
import yt_dlp
from asyncio import sleep
from threading import Thread
from os import makedirs, path as ospath
from colab_leecher.utility.handler import cancelTask  # Assuming this is part of your setup
from colab_leecher.utility.variables import YTDL, MSG, Messages, Paths
from colab_leecher.utility.helper import getTime, keyboard, sizeUnit, status_bar, sysINFO

# FIX: Add this to install ffprobe for audio checking (run once in Colab: !apt install ffmpeg)
# (It's lightweight and helps verify audio post-download)

async def YTDL_Status(link, num):
    global Messages, YTDL
    name = await get_YT_Name(link)
    Messages.status_head = f"<b>📥 DOWNLOADING FROM » </b><i>🔗Link {str(num).zfill(2)}</i>\n\n<code>{name}</code>\n"

    YTDL_Thread = Thread(target=YouTubeDL, name="YouTubeDL", args=(link,))
    YTDL_Thread.start()

    while YTDL_Thread.is_alive():  # Until ytdl is downloading
        if YTDL.header:
            sys_text = sysINFO()
            message = YTDL.header
            try:
                await MSG.status_msg.edit_text(text=Messages.task_msg + Messages.status_head + message + sys_text, reply_markup=keyboard())
            except Exception:
                pass
        else:
            try:
                await status_bar(
                    down_msg=Messages.status_head,
                    speed=YTDL.speed,
                    percentage=float(YTDL.percentage),
                    eta=YTDL.eta,
                    done=YTDL.done,
                    left=YTDL.left,
                    engine="Xr-YtDL 🏮",
                )
            except Exception:
                pass

        await sleep(2.5)


class MyLogger:
    def __init__(self):
        pass

    def debug(self, msg):
        global YTDL
        if "item" in str(msg):
            msgs = msg.split(" ")
            YTDL.header = f"\n⏳ __Getting Video Information {msgs[-3]} of {msgs[-1]}__"

    @staticmethod
    def warning(msg):
        pass

    @staticmethod
    def error(msg):
        # if msg != "ERROR: Cancelling...":
        # print(msg)
        pass


def YouTubeDL(url):
    global YTDL

    def my_hook(d):
        global YTDL

        if d["status"] == "downloading":
            total_bytes = d.get("total_bytes", 0)  # Use 0 as default if total_bytes is None
            dl_bytes = d.get("downloaded_bytes", 0)
            percent = d.get("downloaded_percent", 0)
            speed = d.get("speed", "N/A")
            eta = d.get("eta", 0)

            if total_bytes:
                percent = round((float(dl_bytes) * 100 / float(total_bytes)), 2)

            YTDL.header = ""
            YTDL.speed = sizeUnit(speed) if speed else "N/A"
            YTDL.percentage = percent
            YTDL.eta = getTime(eta) if eta else "N/A"
            YTDL.done = sizeUnit(dl_bytes) if dl_bytes else "N/A"
            YTDL.left = sizeUnit(total_bytes) if total_bytes else "N/A"

        elif d["status"] == "downloading fragment":
            # log_str = d["message"]
            # print(log_str, end="")
            pass
        else:
            logging.info(d)

    ydl_opts = {
        # FIX: Change to merge best video + audio explicitly (this solves no-sound for HLS/m3u8)
        "format": "bestvideo+bestaudio/best",
        "allow_multiple_video_streams": True,
        "allow_multiple_audio_streams": True,
        "writethumbnail": True,
        "concurrent-fragments": 4,  # FIX: Corrected key (was "--concurrent-fragments" – yt-dlp uses this without dashes in opts)
        "allow_playlist_files": True,
        "overwrites": True,
        # FIX: Enhanced postprocessors – first merge video/audio with FFmpeg, then convert to MP4
        "postprocessors": [
            {
                "key": "FFmpegMerger",  # FIX: Add this to merge streams if separate
            },
            {
                "key": "FFmpegVideoConvertor",
                "preferedformat": "mp4",
            },
            # FIX: Optional: Embed subtitles into the video if available
            {
                "key": "FFmpegEmbedSubtitle",
            },
        ],
        "progress_hooks": [my_hook],
        "subtitlesformat": "srt",  # FIX: Moved from 'writesubtitles' to proper key for embedding
        "writesubtitles": True,  # Enable subtitles download
        "logger": MyLogger(),
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        if not ospath.exists(Paths.thumbnail_ytdl):
            makedirs(Paths.thumbnail_ytdl)
        try:
            info_dict = ydl.extract_info(url, download=False)
            YTDL.header = "⌛ __Please WAIT a bit...__"
            if "_type" in info_dict and info_dict["_type"] == "playlist":
                playlist_name = info_dict["title"] 
                if not ospath.exists(ospath.join(Paths.down_path, playlist_name)):
                    makedirs(ospath.join(Paths.down_path, playlist_name))
                ydl_opts["outtmpl"] = {
                    "default": f"{Paths.down_path}/{playlist_name}/%(title)s.%(ext)s",
                    "thumbnail": f"{Paths.thumbnail_ytdl}/%(id)s.%(ext)s",
                }
                for entry in info_dict["entries"]:
                    video_url = entry["webpage_url"]
                    try:
                        ydl.download([video_url])
                    except yt_dlp.utils.DownloadError as e:
                        if e.exc_info[0] == 36:
                            ydl_opts["outtmpl"] = {
                                "default": f"{Paths.down_path}/%(id)s.%(ext)s",
                                "thumbnail": f"{Paths.thumbnail_ytdl}/%(id)s.%(ext)s",
                            }
                            ydl.download([video_url])
                    # FIX: Check for audio after each download
                    check_audio(ydl_opts["outtmpl"]["default"].replace("%(title)s.%(ext)s", entry["title"] + ".mp4"))
            else:
                YTDL.header = ""
                ydl_opts["outtmpl"] = {
                    "default": f"{Paths.down_path}/%(id)s.%(ext)s",
                    "thumbnail": f"{Paths.thumbnail_ytdl}/%(id)s.%(ext)s",
                }
                try:
                    ydl.download([url])
                except yt_dlp.utils.DownloadError as e:
                    if e.exc_info[0] == 36:
                        ydl_opts["outtmpl"] = {
                            "default": f"{Paths.down_path}/%(id)s.%(ext)s",
                            "thumbnail": f"{Paths.thumbnail_ytdl}/%(id)s.%(ext)s",
                        }
                        ydl.download([url])
                # FIX: Check for audio
                check_audio(ydl_opts["outtmpl"]["default"].replace("%(id)s.%(ext)s", info_dict["id"] + ".mp4"))
        except Exception as e:
            logging.error(f"YTDL ERROR: {e}")


# FIX: New function to verify audio presence (uses ffprobe)
def check_audio(file_path):
    import subprocess
    try:
        result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'default=noprint_wrappers=1:nokey=1', file_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if not result.stdout:
            logging.warning(f"No audio detected in {file_path} – Attempting remux fix...")
            fixed_path = file_path.replace(".mp4", "_fixed.mp4")
            subprocess.run(['ffmpeg', '-i', file_path, '-c', 'copy', '-bsf:a', 'aac_adtstoasc', fixed_path])
            logging.info(f"Fixed audio remux saved to {fixed_path}")
        else:
            logging.info(f"Audio detected in {file_path}")
    except Exception as e:
        logging.error(f"Audio check failed: {e}")


async def get_YT_Name(link):
    with yt_dlp.YoutubeDL({"logger": MyLogger()}) as ydl:
        try:
            info = ydl.extract_info(link, download=False)
            if "title" in info and info["title"]: 
                return info["title"]
            else:
                return "UNKNOWN DOWNLOAD NAME"
        except Exception as e:
            await cancelTask(f"Can't Download from this link. Because: {str(e)}")
            return "UNKNOWN DOWNLOAD NAME"
