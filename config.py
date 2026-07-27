import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_PATH = "data.db"
DOWNLOAD_DIR = "downloads"
MAX_DAILY_DOWNLOADS = 15
TELEGRAM_FILE_LIMIT_MB = 48
