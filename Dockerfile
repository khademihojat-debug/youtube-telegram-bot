FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# نصب وابستگی‌های سیستمی لازم
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# مسیرهای پیش‌فرض دیتا
RUN mkdir -p /app/data/downloads

ENV DATA_DIR=/app/data
ENV DB_PATH=/app/data/data.db

CMD ["python", "bot.py"]
