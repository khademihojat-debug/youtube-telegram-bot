FROM python:3.11-slim

WORKDIR /app

COPY . /app
COPY cookies.txt /app/cookies.txt

RUN pip install --no-cache-dir -r requirements.txt

ENV PORT=8080

CMD ["python", "bot.py"]
