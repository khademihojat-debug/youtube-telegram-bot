import os
import asyncio
import inspect
import logging
import yt_dlp
from typing import Dict, Optional, Tuple
import time

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = os.path.join(os.environ.get("DATA_DIR", "./data"), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

COOKIE_FILE = os.environ.get("COOKIE_FILE")

# player clients to try — android/ios often bypass the "sign in to confirm
# you're not a bot" block that hits plain "web" requests from datacenter IPs
YOUTUBE_PLAYER_CLIENTS = ["android", "web"]


def get_cookie_file() -> Optional[str]:
    if COOKIE_FILE and os.path.exists(COOKIE_FILE):
        return COOKIE_FILE
    return None


def _base_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        # NOTE: ignoreerrors is intentionally OFF. With it on, yt-dlp
        # swallows the real failure (bot-check, 403, etc.) and just
        # returns None, which is why you were seeing the generic
        # "Could not extract video info" message instead of the real cause.
        "ignoreerrors": False,
        "extractor_args": {
            "youtube": {
                "player_client": YOUTUBE_PLAYER_CLIENTS,
            }
        },
    }
    cookie = get_cookie_file()
    if cookie:
        opts["cookiefile"] = cookie
    return opts


class ProgressHook:
    def __init__(self, progress_callback):
        self.progress_callback = progress_callback
        self.last_update = 0

    def __call__(self, data):
        if data.get("status") != "downloading" or not self.progress_callback:
            return

        downloaded = data.get("downloaded_bytes", 0)
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        percent = int((downloaded / total) * 100) if total else 0

        now = time.time()
        if now - self.last_update <= 1 and percent < 100:
            return

        self.last_update = now
        result = self.progress_callback(percent)

        if inspect.isawaitable(result):
            try:
                asyncio.run(result)
            except RuntimeError:
                pass


def get_available_qualities(link: str) -> Dict[str, str]:
    ydl_opts = _base_opts()

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=False)

            if info is None:
                logger.error(f"extract_info returned None for link: {link}")
                return {"best": "best"}

            if "entries" in info:
                info = info["entries"][0]
                if info is None:
                    return {"best": "best"}

            formats = info.get("formats", [])
            qualities = {}

            for fmt in formats:
                height = fmt.get("height")
                if not height or fmt.get("vcodec") == "none":
                    continue

                label = f"{height}p"
                qualities.setdefault(label, fmt["format_id"])

            def sort_key(item):
                label = item[0]
                try:
                    return int(label.rstrip("p"))
                except ValueError:
                    return 0

            sorted_qualities = dict(
                sorted(qualities.items(), key=sort_key, reverse=True)
            )

            return sorted_qualities if sorted_qualities else {"best": "best"}

    except Exception as e:
        # Log the REAL reason (bot-check, 403, private video, etc.) instead
        # of silently hiding it. Check your server logs when this happens.
        logger.error(f"get_available_qualities failed for {link}: {e}")
        return {"best": "best"}


def _download_video_sync(
    link: str,
    quality: str,
    progress_callback=None
) -> Tuple[str, Optional[str]]:
    fmt = "bestvideo+bestaudio/best" if quality == "best" else f"{quality}+bestaudio/best"

    ydl_opts = _base_opts()
    ydl_opts.update({
        "format": fmt,
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        "merge_output_format": "mp4",
        "writethumbnail": True,
    })

    if progress_callback:
        ydl_opts["progress_hooks"] = [ProgressHook(progress_callback)]

    cookie = get_cookie_file()

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            if info is None:
                raise Exception("Could not extract video info")

            filename = ydl.prepare_filename(info)
            if not filename.endswith(".mp4"):
                base = os.path.splitext(filename)[0]
                if os.path.exists(base + ".mp4"):
                    filename = base + ".mp4"

            thumb = None
            if info.get("thumbnails"):
                try:
                    ydl_opts_thumb = {
                        "quiet": True,
                        "no_warnings": True,
                        "skip_download": True,
                        "writethumbnail": True,
                        "outtmpl": os.path.splitext(filename)[0],
                    }

                    if cookie:
                        ydl_opts_thumb["cookiefile"] = cookie

                    with yt_dlp.YoutubeDL(ydl_opts_thumb) as ydl_thumb:
                        ydl_thumb.download([link])

                    for ext in [".jpg", ".jpeg", ".png", ".webp"]:
                        test_path = os.path.splitext(filename)[0] + ext
                        if os.path.exists(test_path):
                            thumb = test_path
                            break
                except Exception:
                    pass

            return filename, thumb

    except Exception as e:
        logger.error(f"_download_video_sync failed for {link} (quality={quality}): {e}")
        if quality != "best":
            return _download_video_sync(link, "best", progress_callback)
        raise


async def download_video(
    link: str,
    quality: str,
    progress_callback=None
) -> Tuple[str, Optional[str]]:
    return await asyncio.to_thread(_download_video_sync, link, quality, progress_callback)


def _download_audio_sync(link: str, bitrate: str = "128", progress_callback=None) -> str:
    ydl_opts = _base_opts()
    ydl_opts.update({
        "format": "bestaudio/best",
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": bitrate,
        }],
    })

    if progress_callback:
        ydl_opts["progress_hooks"] = [ProgressHook(progress_callback)]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            if info is None:
                raise Exception("Could not extract audio info")

            filename = ydl.prepare_filename(info)
            filename = os.path.splitext(filename)[0] + ".mp3"
            return filename

    except Exception as e:
        logger.error(f"_download_audio_sync (mp3 convert) failed for {link}: {e}")

        ydl_opts_no_convert = _base_opts()
        ydl_opts_no_convert.update({
            "format": "bestaudio/best",
            "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        })

        if progress_callback:
            ydl_opts_no_convert["progress_hooks"] = [ProgressHook(progress_callback)]

        with yt_dlp.YoutubeDL(ydl_opts_no_convert) as ydl:
            info = ydl.extract_info(link, download=True)
            if info is None:
                raise Exception("Could not extract audio info")

            filename = ydl.prepare_filename(info)
            return filename


async def download_audio(link: str, bitrate: str = "128", progress_callback=None) -> str:
    return await asyncio.to_thread(_download_audio_sync, link, bitrate, progress_callback)


def is_playlist(link: str) -> bool:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
    }

    cookie = get_cookie_file()
    if cookie:
        ydl_opts["cookiefile"] = cookie

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=False)
            return bool(info and "entries" in info and len(info["entries"]) > 1)
    except Exception as e:
        logger.warning(f"is_playlist check failed for {link}: {e}")
        return False
