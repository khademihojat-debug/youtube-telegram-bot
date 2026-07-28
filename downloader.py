import os
import asyncio
import yt_dlp
from typing import Dict, Optional, Tuple

DOWNLOAD_DIR = os.environ.get("DATA_DIR", "./data") + "/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

COOKIE_FILE = os.environ.get("COOKIE_FILE", "cookies.txt")

def get_available_qualities(link: str) -> Dict[str, str]:
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=False)
            if info is None:
                return {'best': 'best'}
            formats = info.get('formats', [])
            qualities = {}
            for f in formats:
                h = f.get('height')
                if h and f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                    qualities[f"{h}p"] = f['format_id']
            return qualities if qualities else {'best': 'best'}
    except Exception:
        return {'best': 'best'}


def _download_video_sync(link: str, quality: str) -> Tuple[str, Optional[str]]:
    # اگر کیفیت انتخاب شده معتبر نیست، از best استفاده کن
    fmt = 'bestvideo+bestaudio/best' if quality == 'best' else f'{quality}+bestaudio/best'

    ydl_opts = {
        'format': fmt,
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            filename = ydl.prepare_filename(info)
            if not filename.endswith('.mp4'):
                base = os.path.splitext(filename)[0]
                if os.path.exists(base + '.mp4'):
                    filename = base + '.mp4'
            return filename, None  # thumbnail را حذف کردیم
    except Exception as e:
        # اگر خطا خورد و quality بهترین نبود، دوباره با best امتحان کن
        if quality != 'best':
            return _download_video_sync(link, 'best')
        raise

async def download_video(link: str, quality: str) -> Tuple[str, Optional[str]]:
    return await asyncio.to_thread(_download_video_sync, link, quality)


def _download_audio_sync(link: str, bitrate: str = '128') -> Tuple[str, Optional[str]]:
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
        'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            filename = ydl.prepare_filename(info)
            filename = os.path.splitext(filename)[0] + '.mp3'
            return filename, None
    except Exception:
        # fallback بدون تبدیل
        ydl_opts_no_convert = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
        }
        with yt_dlp.YoutubeDL(ydl_opts_no_convert) as ydl:
            info = ydl.extract_info(link, download=True)
            filename = ydl.prepare_filename(info)
            return filename, None

async def download_audio(link: str, bitrate: str = '128') -> Tuple[str, Optional[str]]:
    return await asyncio.to_thread(_download_audio_sync, link, bitrate)
