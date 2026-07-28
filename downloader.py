import os
import asyncio
import yt_dlp
from typing import Dict, Optional, Tuple

# ========== تنظیمات ==========
DOWNLOAD_DIR = os.environ.get("DATA_DIR", "./data") + "/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# خواندن مسیر کوکی از متغیر محیطی (پیش‌فرض: cookies.txt در همان پوشه)
COOKIE_FILE = os.environ.get("COOKIE_FILE", "cookies.txt")

def get_available_qualities(link: str) -> Dict[str, str]:
    """
    استخراج لیست کیفیت‌های موجود برای یک لینک.
    فقط فرمت‌هایی که هم ویدیو و هم صدا دارند برمی‌گرداند.
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'cookiefile': COOKIE_FILE,  # استفاده از کوکی
        'extract_flat': False,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=False)
            if info is None:
                return {'best': 'best'}

            formats = info.get('formats', [])
            qualities = {}
            for f in formats:
                height = f.get('height')
                if height and f.get('vcodec') != 'none':
                    acodec = f.get('acodec')
                    if acodec and acodec != 'none':
                        qualities[f'{height}p'] = f['format_id']

            if not qualities:
                return {'best': 'best'}
            return qualities

    except Exception:
        return {'best': 'best'}


def _download_video_sync(link: str, quality: str) -> Tuple[str, Optional[str]]:
    """
    دانلود ویدیو با کیفیت مشخص (همراه با صدا).
    اگر کیفیت انتخابی فقط ویدیو باشد، به فرمت کامل fallback می‌کند.
    """
    if quality == 'best':
        fmt = 'bestvideo+bestaudio/best'
    else:
        fmt = f'{quality}+bestaudio/best'

    ydl_opts = {
        'format': fmt,
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'cookiefile': COOKIE_FILE,  # استفاده از کوکی
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            filename = ydl.prepare_filename(info)
            # اگر پسوند mp4 نبود، تصحیح می‌کنیم
            if not filename.endswith('.mp4'):
                base = os.path.splitext(filename)[0]
                if os.path.exists(base + '.mp4'):
                    filename = base + '.mp4'
            return filename, None

    except Exception as e:
        if quality != 'best':
            return _download_video_sync(link, 'best')
        raise


async def download_video(link: str, quality: str) -> Tuple[str, Optional[str]]:
    return await asyncio.to_thread(_download_video_sync, link, quality)


def _download_audio_sync(link: str, bitrate: str = '128') -> Tuple[str, Optional[str]]:
    """
    دانلود فقط صدا به صورت MP3 با بیت‌ریت مشخص.
    """
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': bitrate,
        }],
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'cookiefile': COOKIE_FILE,  # استفاده از کوکی
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            filename = ydl.prepare_filename(info)
            filename = os.path.splitext(filename)[0] + '.mp3'
            return filename, None

    except Exception:
        # اگر تبدیل با FFmpeg مشکل داشت، بدون تبدیل دانلود کن
        ydl_opts_no_convert = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'cookiefile': COOKIE_FILE,
        }
        with yt_dlp.YoutubeDL(ydl_opts_no_convert) as ydl:
            info = ydl.extract_info(link, download=True)
            filename = ydl.prepare_filename(info)
            return filename, None


async def download_audio(link: str, bitrate: str = '128') -> Tuple[str, Optional[str]]:
    return await asyncio.to_thread(_download_audio_sync, link, bitrate)
