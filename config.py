import os
from pathlib import Path


BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
BOT_MODE = os.getenv("BOT_MODE", "webhook").strip().lower()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", "8080"))
MAX_DAILY_DOWNLOADS = int(os.getenv("MAX_DAILY_DOWNLOADS", "15"))
TELEGRAM_FILE_LIMIT_MB = int(os.getenv("TELEGRAM_FILE_LIMIT_MB", "48"))
COOKIE_FILE = os.getenv("COOKIE_FILE", "/tmp/cookies.txt")


def _ensure_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _resolve_storage_dir() -> Path:
    candidates = [
        os.getenv("DATA_DIR"),
        os.getenv("RAILWAY_VOLUME_MOUNT_PATH"),
        "/app/data",
        "./data",
    ]

    for candidate in candidates:
        if not candidate:
            continue

        path = Path(candidate).expanduser()
        if _ensure_writable_dir(path):
            return path.resolve()

    raise RuntimeError("Could not find a writable storage directory")


STORAGE_DIR = _resolve_storage_dir()
DB_PATH = str(STORAGE_DIR / "data.db")
DOWNLOAD_DIR = STORAGE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
