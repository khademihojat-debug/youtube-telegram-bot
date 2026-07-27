import asyncio
import os
from pathlib import Path
from typing import Tuple, Optional

import requests
import yt_dlp
from config import DOWNLOAD_DIR, TELEGRAM_FILE_LIMIT_MB

DOWNLOAD_PATH = Path(DOWNLOAD_DIR)
DOWNLOAD_PATH.mkdir(exist_ok=True)

def upload_to_pixeldrain(file_path: str) -> Optional[str]:
    url = "https://pixeldrain.com/api/file"
    try:
        with open(file_path, "rb") as f:
            resp = requests.post(url, files={"file": f}, timeout=300)
        if resp.status_code == 200:
            fid = resp.json().get("id")
            if fid:
                return f"https://pixeldrain.com/u/{fid}"
    except Exception:
        return None
    return None

def _download_video_sync(link: str, quality: int) -> Tuple[str, Optional[str]]:
    outtmpl = str(DOWNLOAD_PATH / f"%(title).180B_%(id)s_{quality}p.%(ext)s")
    ydl_opts = {
        "format": f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "merge_output_format": "mp4",
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(link, download=True)
        filename = ydl.prepare_filename(info)
        thumb = info.get("thumbnail")
        return filename, thumb

def _download_audio_sync(link: str, bitrate: str) -> Tuple[str, Optional[str]]:
    outtmpl = str(DOWNLOAD_PATH / f"audio_%(id)s_{bitrate}.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": bitrate,
            }
        ],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(link, download=True)
        filename = ydl.prepare_filename(info).rsplit(".", 1)[0] + ".mp3"
        thumb = info.get("thumbnail")
        return filename, thumb

async def download_video(link: str, quality: int) -> Tuple[str, Optional[str]]:
    return await asyncio.to_thread(_download_video_sync, link, quality)

async def download_audio(link: str, bitrate: str) -> Tuple[str, Optional[str]]:
    return await asyncio.to_thread(_download_audio_sync, link, bitrate)

def get_quality_caption(quality: str) -> str:
    if quality == "a128":
        return "✅ فایل صوتی 128kbps آماده شد!"
    if quality == "a320":
        return "✅ فایل صوتی 320kbps آماده شد!"
    return f"✅ ویدیو {quality}p آماده شد!"

async def send_file_or_link(query, file_path: str, quality: str) -> Optional[str]:
    size_mb = os.path.getsize(file_path) / (1024 * 1024)

    if size_mb > TELEGRAM_FILE_LIMIT_MB:
        await query.message.reply_text(
            f"⚠️ حجم فایل {int(size_mb)}MB است، روی Pixeldrain آپلود می‌شود..."
        )
        pix_url = await asyncio.to_thread(upload_to_pixeldrain, file_path)
        if pix_url:
            await query.message.reply_text(f"✅ لینک مستقیم:\n{pix_url}")
            return pix_url

    await query.message.reply_document(
        document=open(file_path, "rb"),
        caption=get_quality_caption(quality),
    )
    return None
