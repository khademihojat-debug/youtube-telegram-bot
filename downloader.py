import os
import asyncio
import yt_dlp
from typing import Dict, List, Optional, Tuple
import time

DOWNLOAD_DIR = os.environ.get("DATA_DIR", "./data") + "/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

COOKIE_FILE = os.environ.get("COOKIE_FILE", "cookies.txt")

class ProgressHook:
    def __init__(self, progress_callback):
        self.progress_callback = progress_callback
        self.last_update = 0

    def __call__(self, d):
        if d['status'] == 'downloading':
            if 'total_bytes' in d:
                percent = d['downloaded_bytes'] / d['total_bytes'] * 100
            elif 'total_bytes_estimate' in d:
                percent = d['downloaded_bytes'] / d['total_bytes_estimate'] * 100
            else:
                percent = 0
            now = time.time()
            if now - self.last_update > 1 or percent >= 100:
                self.last_update = now
                self.progress_callback(int(percent))

def get_available_qualities(link: str) -> Dict[str, str]:
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
    }
    cookie = COOKIE_FILE if os.path.exists(COOKIE_FILE) else None
    if cookie:
        ydl_opts['cookiefile'] = cookie

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=False)
            if info is None:
                return {'best': 'best'}
            # اگر پلی‌لیست بود، فقط اولین ویدیو را در نظر بگیر
            if 'entries' in info:
                info = info['entries'][0]
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

def _download_video_sync(link: str, quality: str, progress_callback=None) -> Tuple[str, Optional[str]]:
    fmt = 'bestvideo+bestaudio/best' if quality == 'best' else f'{quality}+bestaudio/best'
    ydl_opts = {
        'format': fmt,
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'writethumbnail': True,
    }
    cookie = COOKIE_FILE if os.path.exists(COOKIE_FILE) else None
    if cookie:
        ydl_opts['cookiefile'] = cookie

    if progress_callback:
        ydl_opts['progress_hooks'] = [ProgressHook(progress_callback)]

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
            # پیدا کردن تام‌نیل
            thumb = None
            if info.get('thumbnails'):
                thumb_url = info['thumbnails'][-1]['url']
                thumb_path = os.path.splitext(filename)[0] + '.jpg'
                # دانلود تام‌نیل با yt-dlp
                try:
                    ydl_opts_thumb = {
                        'quiet': True,
                        'skip_download': True,
                        'writethumbnail': True,
                        'outtmpl': os.path.splitext(filename)[0],
                    }
                    if cookie:
                        ydl_opts_thumb['cookiefile'] = cookie
                    with yt_dlp.YoutubeDL(ydl_opts_thumb) as ydl_thumb:
                        ydl_thumb.download([link])
                    # پیدا کردن فایل تام‌نیل دانلود شده
                    for ext in ['.jpg', '.jpeg', '.png', '.webp']:
                        test_path = os.path.splitext(filename)[0] + ext
                        if os.path.exists(test_path):
                            thumb = test_path
                            break
                except:
                    pass
            return filename, thumb
    except Exception as e:
        if quality != 'best':
            return _download_video_sync(link, 'best', progress_callback)
        raise

async def download_video(link: str, quality: str, progress_callback=None) -> Tuple[str, Optional[str]]:
    return await asyncio.to_thread(_download_video_sync, link, quality, progress_callback)

def _download_audio_sync(link: str, bitrate: str = '128', progress_callback=None) -> str:
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
    cookie = COOKIE_FILE if os.path.exists(COOKIE_FILE) else None
    if cookie:
        ydl_opts['cookiefile'] = cookie

    if progress_callback:
        ydl_opts['progress_hooks'] = [ProgressHook(progress_callback)]

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
        if cookie:
            ydl_opts_no_convert['cookiefile'] = cookie
        with yt_dlp.YoutubeDL(ydl_opts_no_convert) as ydl:
            info = ydl.extract_info(link, download=True)
            if info is None:
                raise Exception("Could not extract audio info")
            filename = ydl.prepare_filename(info)
            return filename

async def download_audio(link: str, bitrate: str = '128', progress_callback=None) -> str:
    return await asyncio.to_thread(_download_audio_sync, link, bitrate, progress_callback)

def is_playlist(link: str) -> bool:
    ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=False)
            return 'entries' in info and len(info['entries']) > 1
    except:
        return False
