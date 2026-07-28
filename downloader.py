import os
import asyncio
import inspect
import yt_dlp
from typing import Dict, Optional, Tuple
import time

DOWNLOAD_DIR = os.path.join(os.environ.get("DATA_DIR", "./data"), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

COOKIE_FILE = os.environ.get("COOKIE_FILE")


def get_cookie_file() -> Optional[str]:
    if COOKIE_FILE and os.path.exists(COOKIE_FILE):
        return COOKIE_FILE
    return None


class ProgressHook:
    def __init__(self, progress_callback):
        self.progress_callback = progress_callback
        self.last_update = 0

    def __call__(self, data):
        if data.get('status') != 'downloading' or not self.progress_callback:
            return

        downloaded = data.get('downloaded_bytes', 0)
        total = data.get('total_bytes') or data.get('total_bytes_estimate')
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
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
    }
    cookie = get_cookie_file()
    if cookie:
        ydl_opts['cookiefile'] = cookie

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=False)
            if info is None:
                return {'best': 'best'}

            if 'entries' in info:
                info = info['entries'][0]
                if info is None:
                    return {'best': 'best'}

            formats = info.get('formats', [])
            qualities = {}
            for fmt in formats:
                height = fmt.get('height')
                if not height or fmt.get('vcodec') == 'none':
                    continue

                label = f"{height}p"
                qualities.setdefault(label, fmt['format_id'])

            def sort_key(item):
                label = item[0]
                try:
                    return int(label.rstrip('p'))
                except ValueError:
                    return 0

            sorted_qualities = dict(sorted(qualities.items(), key=sort_key, reverse=True))
            return sorted_qualities if sorted_qualities else {'best': 'best'}
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
    cookie = get_cookie_file()
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

            thumb = None
            if info.get('thumbnails'):
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
                    for ext in ['.jpg', '.jpeg', '.png', '.webp']:
                        test_path = os.path.splitext(filename)[0] + ext
                        if os.path.exists(test_path):
                            thumb = test_path
                            break
                except Exception:
                    pass
            return filename, thumb
    except Exception:
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
    cookie = get_cookie_file()
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
        ydl_opts_no_convert = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
        }
        if cookie:
            ydl_opts_no_convert['cookiefile'] = cookie
        if progress_callback:
            ydl_opts_no_convert['progress_hooks'] = [ProgressHook(progress_callback)]

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
    cookie = get_cookie_file()
    if cookie:
        ydl_opts['cookiefile'] = cookie

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=False)
            return bool(info and 'entries' in info and len(info['entries']) > 1)
    except Exception:
        return False
