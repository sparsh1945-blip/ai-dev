# --- YouTube URL -> MP3/MP4 downloader ---
FROM python:3.12-slim

# ffmpeg is required by yt-dlp to extract/convert audio (mp3) and merge video streams
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates/ templates/

RUN mkdir -p /app/downloads

EXPOSE 5000

# Use gunicorn in production; single worker keeps disk cleanup thread simple
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "300", "app:app"]
