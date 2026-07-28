import os
import asyncio
import yt_dlp

DOWNLOAD_DIR = "./data/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def get_available_qualities(link: str):
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
            info = ydl.extract_info(link, download=False)
            formats = info.get('formats', [])
            qualities = {}
            for f in formats:
                h = f.get('height')
                if h and f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                    qualities[f"{h}p"] = f['format_id']
            return qualities if qualities else {"best": "best"}
    except:
        return {"best": "best"}

def _download_video_sync(link, quality):
    fmt = 'bestvideo+bestaudio/best' if quality == 'best' else f'{quality}+bestaudio/best'
    opts = {
        'format': fmt,
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(link, download=True)
        return ydl.prepare_filename(info), None

def _download_audio_sync(link, bitrate):
    opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': bitrate}],
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(link, download=True)
        filename = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')
        return filename, None

async def download_video(link, quality):
    return await asyncio.to_thread(_download_video_sync, link, quality)

async def download_audio(link, bitrate):
    return await asyncio.to_thread(_download_audio_sync, link, bitrate)
