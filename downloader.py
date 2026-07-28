import os
import asyncio
import yt_dlp
from typing import Dict, Optional, Tuple

# تنظیمات مسیرها (از متغیرهای محیطی خوانده می‌شود)
DOWNLOAD_DIR = os.environ.get("DATA_DIR", "./data") + "/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def get_available_qualities(link: str) -> Dict[str, str]:
    """
    استخراج لیست کیفیت‌های موجود برای یک لینک.
    در صورت بروز هر خطا، یک لیست پیش‌فرض شامل 'best' برمی‌گرداند.
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,          # مهم: خطاهای فرمت را نادیده می‌گیرد
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
                    qualities[f'{height}p'] = f['format_id']
            # اگر هیچ فرمت ویدیویی نبود، بهترین را انتخاب کن
            if not qualities:
                return {'best': 'best'}
            return qualities
    except Exception:
        # در صورت هر گونه خطای غیرمنتظره، لیست پیش‌فرض
        return {'best': 'best', '720p': '22', '360p': '18'}


def _download_video_sync(link: str, quality: str) -> Tuple[str, Optional[str]]:
    """
    دانلود همزمان ویدئو با کیفیت مشخص.
    اگر کیفیت درخواستی موجود نباشد، به 'best' fallback می‌کند.
    """
    if quality == 'best':
        fmt = 'bestvideo+bestaudio/best'
    else:
        fmt = quality

    ydl_opts = {
        'format': fmt,
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'writethumbnail': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            filename = ydl.prepare_filename(info)
            # پیدا کردن فایل thumbnail
            thumb = None
            if info.get('thumbnails'):
                thumb_url = info['thumbnails'][-1]['url']
                # دانلود thumbnail (اختیاری)
            return filename, thumb
    except Exception as e:
        # اگر خطا به دلیل عدم دسترسی به فرمت بود و کیفیت 'best' نبود، دوباره با 'best' تلاش کن
        if "Requested format is not available" in str(e) and quality != 'best':
            return _download_video_sync(link, 'best')
        raise


async def download_video(link: str, quality: str) -> Tuple[str, Optional[str]]:
    """
    نسخه ناهمگام دانلود ویدئو.
    """
    return await asyncio.to_thread(_download_video_sync, link, quality)


async def download_audio(link: str, bitrate: str = '128') -> Tuple[str, Optional[str]]:
    """
    استخراج صدا به صورت MP3 با بیت‌ریت مشخص (پیش‌فرض ۱۲۸).
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
            filename = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')
            return filename, None
    except Exception as e:
        if "Requested format is not available" in str(e):
            # اگر خطا داشت، دوباره با تنظیمات ساده‌تر تلاش کن
            ydl_opts['format'] = 'bestaudio'
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(link, download=True)
                filename = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')
                return filename, None
        raise
