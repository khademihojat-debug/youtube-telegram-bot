import os
import yt_dlp
from config import DOWNLOAD_PATH


def download_video(url):
    ydl_opts = {
        "format": "bestvideo+bestaudio/best",
        "outtmpl": os.path.join(DOWNLOAD_PATH, "%(title)s.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

        if not filename.endswith(".mp4"):
            base = os.path.splitext(filename)[0]
            if os.path.exists(base + ".mp4"):
                filename = base + ".mp4"

        return {
            "title": info.get("title"),
            "duration": info.get("duration"),
            "file": filename,
        }


def download_audio(url):
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(DOWNLOAD_PATH, "%(title)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

        return {
            "title": info.get("title"),
            "duration": info.get("duration"),
            "file": os.path.join(DOWNLOAD_PATH, f"{info['title']}.mp3"),
        }
