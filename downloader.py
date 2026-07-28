import os
import asyncio
import yt_dlp
from typing import Dict

DOWNLOAD_DIR = os.environ.get("DATA_DIR", "./data") + "/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def get_available_qualities(link: str) -> Dict[str, str]:
    """
    دریافت لیست کیفیت‌های موجود برای یک لینک.
    فقط فرمت‌هایی که هم ویدیو و هم صدا دارند.
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
    }
    
    # اگر فایل کوکی وجود داشت، به yt-dlp بده
    cookie_file = os.environ.get("COOKIE_FILE")
    if cookie_file and os.path.exists(cookie_file):
        ydl_opts['cookiefile'] = cookie_file

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
            
    except Exception as e:
        return {'best': 'best'}

def _download_video_sync(link: str, quality: str) -> str:
    fmt = 'bestvideo+bestaudio/best' if quality == 'best' else f'{quality}+bestaudio/best'
    
    ydl_opts = {
        'format': fmt,
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
    }
    
    cookie_file = os.environ.get("COOKIE_FILE")
    if cookie_file and os.path.exists(cookie_file):
        ydl_opts['cookiefile'] = cookie_file
        
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            if info is None:
                raise Exception("Could not extract video info")
            filename = ydl.prepare_filename(info)
            if not filename.endswith('.mp4'):
                base = os.path.splitext(filename)[0]
                if os.path.exists(base + '.mp4'):
                    filename = base + '.mp4'
            return filename
    except Exception as e:
        if quality != 'best':
            return _download_video_sync(link, 'best')
        raise

async def download_video(link: str, quality: str) -> str:
    return await asyncio.to_thread(_download_video_sync, link, quality)

def _download_audio_sync(link: str, bitrate: str = '128') -> str:
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
    
    cookie_file = os.environ.get("COOKIE_FILE")
    if cookie_file and os.path.exists(cookie_file):
        ydl_opts['cookiefile'] = cookie_file
        
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            if info is None:
                raise Exception("Could not extract audio info")
            filename = ydl.prepare_filename(info)
            filename = os.path.splitext(filename)[0] + '.mp3'
            return filename
    except Exception:
        # fallback بدون تبدیل
        ydl_opts_no_convert = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
        }
        if cookie_file and os.path.exists(cookie_file):
            ydl_opts_no_convert['cookiefile'] = cookie_file
            
        with yt_dlp.YoutubeDL(ydl_opts_no_convert) as ydl:
            info = ydl.extract_info(link, download=True)
            if info is None:
                raise Exception("Could not extract audio info")
            filename = ydl.prepare_filename(info)
            return filename

async def download_audio(link: str, bitrate: str = '128') -> str:
    return await asyncio.to_thread(_download_audio_sync, link, bitrate)
