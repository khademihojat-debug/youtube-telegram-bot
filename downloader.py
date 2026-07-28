import asyncio
import mimetypes
import os
import shutil
from pathlib import Path
from typing import Optional

from telegram import Message
from yt_dlp import YoutubeDL

from config import DOWNLOAD_DIR


DOWNLOAD_PATH = Path(DOWNLOAD_DIR)
DOWNLOAD_PATH.mkdir(parents=True, exist_ok=True)
HAS_FFMPEG = shutil.which("ffmpeg") is not None


class DownloadError(Exception):
    pass


def _safe_prepare_filename(ydl: YoutubeDL, info: dict, forced_ext: Optional[str] = None) -> str:
    base_path = Path(ydl.prepare_filename(info))
    if forced_ext:
        base_path = base_path.with_suffix(f".{forced_ext}")
    return str(base_path)


def _video_format_selector(max_height: int) -> str:
    max_height = int(max_height)

    if HAS_FFMPEG:
        return (
            f"best[ext=mp4][height<={max_height}]"
            f"/best[height<={max_height}]"
            f"/bestvideo[ext=mp4][height<={max_height}]+bestaudio[ext=m4a]"
            f"/bestvideo[height<={max_height}]+bestaudio"
            f"/best"
        )

    return (
        f"best[ext=mp4][height<={max_height}]"
        f"/best[height<={max_height}]"
        f"/best"
    )


def _audio_options(bitrate: str) -> dict:
    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "outtmpl": str(DOWNLOAD_PATH / "%(title).180B [%(id)s].%(ext)s"),
        "restrictfilenames": False,
    }

    if HAS_FFMPEG:
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": str(bitrate),
            }
        ]

    return opts


def _video_options(quality: int) -> dict:
    opts = {
        "format": _video_format_selector(quality),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "outtmpl": str(DOWNLOAD_PATH / "%(title).180B [%(id)s].%(ext)s"),
        "restrictfilenames": False,
    }

    if HAS_FFMPEG:
        opts["merge_output_format"] = "mp4"

    return opts


def _download_audio_sync(link: str, bitrate: str):
    ydl_opts = _audio_options(bitrate)

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(link, download=True)
        thumb = info.get("thumbnail")

        if HAS_FFMPEG:
            filename = _safe_prepare_filename(ydl, info, forced_ext="mp3")
        else:
            filename = _safe_prepare_filename(ydl, info)

    if not os.path.exists(filename):
        requested = info.get("requested_downloads") or []
        if requested:
            guessed = requested[0].get("filepath")
            if guessed and os.path.exists(guessed):
                filename = guessed

    if not os.path.exists(filename):
        raise FileNotFoundError(f"Audio file not found after download: {filename}")

    return filename, thumb


def _download_video_sync(link: str, quality: int):
    ydl_opts = _video_options(quality)

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(link, download=True)
        thumb = info.get("thumbnail")

        ext = "mp4" if HAS_FFMPEG else info.get("ext")
        filename = _safe_prepare_filename(ydl, info, forced_ext=ext)

    if not os.path.exists(filename):
        requested = info.get("requested_downloads") or []
        for item in requested:
            guessed = item.get("filepath")
            if guessed and os.path.exists(guessed):
                filename = guessed
                break

    if not os.path.exists(filename):
        raise FileNotFoundError(f"Video file not found after download: {filename}")

    return filename, thumb


async def download_audio(link: str, bitrate: str):
    return await asyncio.to_thread(_download_audio_sync, link, bitrate)


async def download_video(link: str, quality: int):
    return await asyncio.to_thread(_download_video_sync, link, quality)


def get_available_qualities(link: str) -> list[int]:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(link, download=False)

    heights: set[int] = set()
    for fmt in info.get("formats", []):
        height = fmt.get("height")
        vcodec = fmt.get("vcodec")
        if height and vcodec and vcodec != "none":
            heights.add(int(height))

    preferred = [144, 240, 360, 480, 720, 1080, 1440, 2160]
    result = [q for q in preferred if q in heights]

    if result:
        return result

    return sorted(heights)


async def send_file_or_link(message: Message, file_path: str, quality: str) -> Optional[str]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)

    mime_type, _ = mimetypes.guess_type(path.name)
    mime_type = mime_type or "application/octet-stream"
    caption = f"✅ آماده شد: {path.name}"
    is_audio = quality.startswith("a") or mime_type.startswith("audio/")
    is_video = mime_type.startswith("video/")

    try:
        with path.open("rb") as file_obj:
            if is_audio:
                await message.reply_audio(
                    audio=file_obj,
                    filename=path.name,
                    caption=caption,
                )
                return None
    except Exception:
        pass

    try:
        with path.open("rb") as file_obj:
            if is_video and not is_audio:
                await message.reply_video(
                    video=file_obj,
                    filename=path.name,
                    caption=caption,
                    supports_streaming=True,
                )
                return None
    except Exception:
        pass

    try:
        with path.open("rb") as file_obj:
            await message.reply_document(
                document=file_obj,
                filename=path.name,
                caption=caption,
            )
            return None
    except Exception as exc:
        raise DownloadError(
            "فایل دانلود شد ولی ارسال آن در تلگرام ناموفق بود. "
            "اگر فایل خیلی بزرگ است، محدودیت ارسال تلگرام یا سرور را بررسی کن."
        ) from exc
