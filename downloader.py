import asyncio
import os
from pathlib import Path
from typing import Optional, Tuple

import requests
import yt_dlp

from config import COOKIE_FILE, DOWNLOAD_DIR, TELEGRAM_FILE_LIMIT_MB


DOWNLOAD_PATH = Path(DOWNLOAD_DIR)
DOWNLOAD_PATH.mkdir(parents=True, exist_ok=True)


def _base_ydl_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    if COOKIE_FILE and Path(COOKIE_FILE).exists():
        opts["cookiefile"] = COOKIE_FILE
    return opts


def get_available_qualities(link: str):
    ydl_opts = _base_ydl_opts()
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(link, download=False)
        formats = info.get("formats", [])

    qualities = sorted(
        {
            int(fmt["height"])
            for fmt in formats
            if fmt.get("height") and int(fmt["height"]) <= 2160
        }
    )
    return qualities


def upload_to_pixeldrain(file_path: str) -> Optional[str]:
    url = "https://pixeldrain.com/api/file"
    try:
        with open(file_path, "rb") as file_obj:
            response = requests.post(url, files={"file": file_obj}, timeout=300)
        if response.status_code == 200:
            file_id = response.json().get("id")
            if file_id:
                return f"https://pixeldrain.com/u/{file_id}"
    except Exception:
        return None
    return None


def resolve_final_path(prepared_filename: str, expected_ext: str) -> str:
    path = Path(prepared_filename)

    if path.suffix.lower() == f".{expected_ext.lower()}" and path.exists():
        return str(path)

    candidate = path.with_suffix(f".{expected_ext}")
    if candidate.exists():
        return str(candidate)

    return str(path)


def _download_video_sync(link: str, quality: int) -> Tuple[str, Optional[str]]:
    outtmpl = str(DOWNLOAD_PATH / f"%(title).180B_%(id)s_{quality}p.%(ext)s")

    ydl_opts = {
        **_base_ydl_opts(),
        "format": f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best",
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(link, download=True)
        filename = resolve_final_path(ydl.prepare_filename(info), "mp4")
        thumb = info.get("thumbnail")
        return filename, thumb


def _download_audio_sync(link: str, bitrate: str) -> Tuple[str, Optional[str]]:
    outtmpl = str(DOWNLOAD_PATH / f"audio_%(title).180B_%(id)s_{bitrate}.%(ext)s")

    ydl_opts = {
        **_base_ydl_opts(),
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
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
        filename = resolve_final_path(ydl.prepare_filename(info), "mp3")
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


async def send_file_or_link(message, file_path: str, quality: str) -> Optional[str]:
    size_mb = os.path.getsize(file_path) / (1024 * 1024)

    if size_mb > TELEGRAM_FILE_LIMIT_MB:
        await message.reply_text(
            f"⚠️ حجم فایل {int(size_mb)}MB است، روی Pixeldrain آپلود می‌شود..."
        )
        pixeldrain_url = await asyncio.to_thread(upload_to_pixeldrain, file_path)
        if pixeldrain_url:
            await message.reply_text(f"✅ لینک مستقیم:\n{pixeldrain_url}")
            return pixeldrain_url
        raise RuntimeError(
            "فایل از محدودیت تلگرام بزرگ‌تر است و آپلود جایگزین هم ناموفق بود."
        )

    with open(file_path, "rb") as file_obj:
        await message.reply_document(
            document=file_obj,
            caption=get_quality_caption(quality),
        )
    return None
