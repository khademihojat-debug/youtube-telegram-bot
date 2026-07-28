import os
import asyncio
import yt_dlp
from typing import Dict, Optional, Tuple

# تنظیمات مسیرها
DOWNLOAD_DIR = os.environ.get("DATA_DIR", "./data") + "/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def get_available_qualities(link: str) -> Dict[str, str]:
    """
    استخراج لیست کیفیت‌های موجود برای یک لینک.
    فقط فرمت‌هایی که هم ویدیو و هم صدا دارند (یا ترکیبی) برمی‌گرداند.
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
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
                # فقط فرمت‌هایی که ویدیو دارند و صدا هم دارند (یا حداقل acodec ندارند یعنی صدا ندارند؟)
                # ما می‌خواهیم فرمت‌هایی که صدا دارند یا ترکیبی هستند
                if height and f.get('vcodec') != 'none':
                    # بررسی می‌کنیم که صدا داشته باشد یا فرمت ترکیبی باشد
                    acodec = f.get('acodec')
                    if acodec and acodec != 'none':
                        # این فرمت هم ویدیو و هم صدا دارد
                        qualities[f'{height}p'] = f['format_id']
                    # اگر acodec='none' یعنی فقط ویدیو است، نادیده می‌گیریم
            
            # اگر هیچ فرمتی با صدا پیدا نشد، از best استفاده کن
            if not qualities:
                return {'best': 'best'}
            return qualities
            
    except Exception:
        return {'best': 'best', '720p': '22', '360p': '18'}


def _download_video_sync(link: str, quality: str) -> Tuple[str, Optional[str]]:
    """
    دانلود ویدیو با کیفیت مشخص (همراه با صدا)
    اگر کیفیت انتخابی فقط ویدیو بدون صدا باشد، به فرمت کامل fallback می‌کند.
    """
    if quality == 'best':
        # بهترین فرمتی که هم ویدیو و هم صدا دارد
        fmt = 'best[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
    else:
        # سعی می‌کنیم با کیفیت انتخاب شده دانلود کنیم، اگر صدا نداشت، بهترین ترکیبی را بگیر
        fmt = f'{quality}+bestaudio/best'

    ydl_opts = {
        'format': fmt,
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            filename = ydl.prepare_filename(info)
            # اگر فایل با پسوند دیگری ساخته شد، به mp4 تغییر بده
            if not filename.endswith('.mp4'):
                base = os.path.splitext(filename)[0]
                if os.path.exists(base + '.mp4'):
                    filename = base + '.mp4'
                elif os.path.exists(filename):
                    # اگر فایل موجود است ولی mp4 نیست، پسوند را تغییر نمی‌دهیم
                    pass
            return filename, None
            
    except Exception as e:
        # اگر خطا خورد، با بهترین کیفیت کامل امتحان کن
        if quality != 'best':
            return _download_video_sync(link, 'best')
        raise


async def download_video(link: str, quality: str) -> Tuple[str, Optional[str]]:
    return await asyncio.to_thread(_download_video_sync, link, quality)


def _download_audio_sync(link: str, bitrate: str = '128') -> Tuple[str, Optional[str]]:
    """
    دانلود فقط صدا به صورت MP3 با بیت‌ریت مشخص
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
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            filename = ydl.prepare_filename(info)
            # تبدیل پسوند به mp3
            filename = os.path.splitext(filename)[0] + '.mp3'
            return filename, None
    except Exception as e:
        # اگر خطا داشت، بدون تبدیل دانلود کن
        ydl_opts_no_convert = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts_no_convert) as ydl:
            info = ydl.extract_info(link, download=True)
            filename = ydl.prepare_filename(info)
            return filename, None


async def download_audio(link: str, bitrate: str = '128') -> Tuple[str, Optional[str]]:
    return await asyncio.to_thread(_download_audio_sync, link, bitrate)
