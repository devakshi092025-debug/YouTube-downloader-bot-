FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp && \
    chmod a+rx /usr/local/bin/yt-dlp

RUN pip install --upgrade pip && \
    pip install \
    python-telegram-bot==21.3 \
    flask==3.0.3 \
    python-dotenv==1.0.0

WORKDIR /app
COPY . .

CMD ["python", "-u", "downloader_bot.py"]
