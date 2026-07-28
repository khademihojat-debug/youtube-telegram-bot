# YouTube Telegram Bot

Telegram bot for downloading YouTube videos and MP3 using `yt-dlp`.

## Features

- Download video in available qualities
- Download MP3 in 128kbps and 320kbps
- SQLite database
- Inline keyboard
- Webhook mode for Render/Railway
- Polling mode for local development
- Automatic fallback to Pixeldrain for large files

## Required environment variables

- `BOT_TOKEN`
- `ADMIN_ID` (optional, default: `0`)
- `BOT_MODE` (`webhook` or `polling`, default: `webhook`)
- `WEBHOOK_URL` (required only in webhook mode)
- `PORT` (optional, default: `8080`)
- `DATA_DIR` (optional)
- `COOKIE_FILE` (optional, default: `cookies.txt`)
- `MAX_DAILY_DOWNLOADS` (optional, default: `15`)
- `TELEGRAM_FILE_LIMIT_MB` (optional, default: `48`)

## Notes

- `ffmpeg` is required for MP3 extraction.
- `cookies.txt` is optional and should not be committed to the repository.
- If no writable `/app/data` path is available, the bot falls back to `./data` automatically.
