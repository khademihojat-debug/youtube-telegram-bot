FROM python:3.11-slim

WORKDIR /app

# نصب وابستگی‌های سیستمی شامل ffmpeg و nodejs برای حل مشکل n-sig
RUN apt-get update && apt-get install -y \
    ffmpeg \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# کپی و نصب وابستگی‌های پایتون
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --upgrade yt-dlp && \
    pip install --no-cache-dir -r requirements.txt

# کپی کل پروژه
COPY . .

# پورت پیش‌فرض
EXPOSE 8080

# اجرای ربات
CMD ["python", "bot.py"]
