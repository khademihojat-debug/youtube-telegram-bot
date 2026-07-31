import os
import time
import asyncio
import inspect
import logging
import requests
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = os.path.join(os.environ.get("DATA_DIR", "./data"), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# آدرس اینستنس خودتون از Cobalt (بدون / در انتها) — باید در Railway ست بشه.
# مثال: https://your-cobalt-instance.up.railway.app
COBALT_API_URL = os.environ.get("COBALT_API_URL", "").rstrip("/")

# چون Cobalt یه دامنه‌ی عمومی داره، هرکسی که آدرسش رو پیدا کنه می‌تونه ازش
# استفاده کنه و هزینه/منابع سرور شما رو مصرف کنه. اگه روی سرویس Cobalt
# متغیر API_AUTH_API_KEY رو ست کرده باشید، همون مقدار رو اینجا هم بذارید تا
# درخواست‌ها احراز هویت بشن.
COBALT_API_KEY = os.environ.get("COBALT_API_KEY", "").strip()

# Cobalt برخلاف yt-dlp نیازی نداره که برای هر لینک لیست کیفیت‌های واقعی رو
# استخراج کنیم — فقط کیفیت دلخواه رو می‌گیره و اگه موجود نباشه نزدیک‌ترین رو
# برمی‌گردونه. پس یه لیست ثابت کافیه.
QUALITY_OPTIONS = {
    "2160p": "2160",
    "1440p": "1440",
    "1080p": "1080",
    "720p": "720",
    "480p": "480",
    "360p": "360",
}


def _cobalt_request(payload: dict) -> dict:
    if not COBALT_API_URL:
        raise Exception(
            "COBALT_API_URL تنظیم نشده — آدرس اینستنس Cobalt خودتون رو در "
            "Environment Variables ست کنید"
        )

    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if COBALT_API_KEY:
        headers["Authorization"] = f"Api-Key {COBALT_API_KEY}"

    resp = requests.post(
        COBALT_API_URL + "/",
        json=payload,
        headers=headers,
        timeout=30,
    )
    data = resp.json()

    if data.get("status") == "error":
        code = data.get("error", {}).get("code", "unknown")
        raise Exception(f"Cobalt error: {code}")

    return data


def _report_progress(progress_callback, percent: int):
    if not progress_callback:
        return
    result = progress_callback(percent)
    if inspect.isawaitable(result):
        try:
            asyncio.run(result)
        except RuntimeError:
            pass


def _download_stream(url: str, dest_path: str, progress_callback=None):
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = r.headers.get("Content-Length") or r.headers.get("Estimated-Content-Length")
        total = int(total) if total else None
        downloaded = 0
        last_update = 0.0

        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    percent = int(downloaded / total * 100)
                    now = time.time()
                    if now - last_update > 1 or percent >= 100:
                        last_update = now
                        _report_progress(progress_callback, percent)


def get_available_qualities(link: str) -> Dict[str, str]:
    return QUALITY_OPTIONS


def is_playlist(link: str) -> bool:
    # Cobalt از پلی‌لیست پشتیبانی نمی‌کنه؛ همیشه به‌عنوان یه ویدیوی تکی
    # پردازش می‌شه (که با محدودیت فعلی ربات هم‌خونی داره).
    return False


def _download_video_sync(
    link: str,
    quality: str,
    progress_callback=None
) -> Tuple[str, Optional[str]]:
    video_quality = "max" if quality == "best" else quality

    data = _cobalt_request({
        "url": link,
        "videoQuality": video_quality,
        "downloadMode": "auto",
        "filenameStyle": "basic",
    })

    status = data.get("status")

    if status in ("tunnel", "redirect"):
        file_url = data["url"]
        filename = data.get("filename") or f"video_{int(time.time())}.mp4"
        dest_path = os.path.join(DOWNLOAD_DIR, filename)
        _download_stream(file_url, dest_path, progress_callback)
        return dest_path, None

    if status == "picker":
        items = data.get("picker") or []
        if not items:
            raise Exception("هیچ آیتم قابل‌دانلودی پیدا نشد")
        # اولویت با ویدیو، ولی اگه پست فقط عکس باشه (مثل کاروسل اینستاگرام)
        # اولین آیتم موجود رو می‌گیریم.
        video_items = [i for i in items if i.get("type") in ("video", "gif")]
        chosen = video_items[0] if video_items else items[0]
        file_url = chosen["url"]
        ext = "mp4" if chosen.get("type") in ("video", "gif") else "jpg"
        filename = f"media_{int(time.time())}.{ext}"
        dest_path = os.path.join(DOWNLOAD_DIR, filename)
        _download_stream(file_url, dest_path, progress_callback)
        return dest_path, None

    if status == "local-processing":
        raise Exception("این ویدیو نیاز به پردازش محلی (remux) داره که فعلاً پشتیبانی نمی‌شه")

    raise Exception(f"پاسخ غیرمنتظره از Cobalt: {status}")


async def download_video(
    link: str,
    quality: str,
    progress_callback=None
) -> Tuple[str, Optional[str]]:
    return await asyncio.to_thread(_download_video_sync, link, quality, progress_callback)


def _download_audio_sync(link: str, bitrate: str = "128", progress_callback=None) -> str:
    data = _cobalt_request({
        "url": link,
        "downloadMode": "audio",
        "audioBitrate": bitrate,
        "audioFormat": "mp3",
        "filenameStyle": "basic",
    })

    status = data.get("status")

    if status in ("tunnel", "redirect"):
        file_url = data["url"]
        filename = data.get("filename") or f"audio_{int(time.time())}.mp3"
        dest_path = os.path.join(DOWNLOAD_DIR, filename)
        _download_stream(file_url, dest_path, progress_callback)
        return dest_path

    if status == "picker":
        audio_url = data.get("audio")
        if not audio_url:
            raise Exception("هیچ فایل صوتی پیدا نشد")
        filename = data.get("audioFilename") or f"audio_{int(time.time())}.mp3"
        dest_path = os.path.join(DOWNLOAD_DIR, filename)
        _download_stream(audio_url, dest_path, progress_callback)
        return dest_path

    raise Exception(f"پاسخ غیرمنتظره از Cobalt: {status}")


async def download_audio(link: str, bitrate: str = "128", progress_callback=None) -> str:
    return await asyncio.to_thread(_download_audio_sync, link, bitrate, progress_callback)
