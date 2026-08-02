import os
import uuid
import threading
import time

from flask import Flask, request, render_template, send_file, jsonify, after_this_request
import yt_dlp

app = Flask(__name__)

DOWNLOAD_DIR = "/app/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Remove files older than 30 minutes so the container doesn't fill up disk
def cleanup_old_files():
    while True:
        now = time.time()
        for fname in os.listdir(DOWNLOAD_DIR):
            fpath = os.path.join(DOWNLOAD_DIR, fname)
            if os.path.isfile(fpath) and now - os.path.getmtime(fpath) > 1800:
                try:
                    os.remove(fpath)
                except OSError:
                    pass
        time.sleep(300)

threading.Thread(target=cleanup_old_files, daemon=True).start()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/download", methods=["POST"])
def download():
    url = request.form.get("url", "").strip()
    fmt = request.form.get("format", "mp3")  # "mp3" or "mp4"

    if not url:
        return jsonify({"error": "Please provide a URL."}), 400

    job_id = str(uuid.uuid4())
    out_template = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")

    if fmt == "mp3":
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": out_template,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "noplaylist": True,
            "quiet": True,
        }
    else:
        ydl_opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": out_template,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "download")
    except Exception as e:
        return jsonify({"error": f"Download failed: {str(e)}"}), 500

    # Find the produced file (extension may differ from what we guessed)
    produced = None
    for fname in os.listdir(DOWNLOAD_DIR):
        if fname.startswith(job_id):
            produced = os.path.join(DOWNLOAD_DIR, fname)
            break

    if not produced or not os.path.exists(produced):
        return jsonify({"error": "File not found after processing."}), 500

    ext = "mp3" if fmt == "mp3" else "mp4"
    safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip() or "download"
    download_name = f"{safe_title}.{ext}"

    @after_this_request
    def remove_file(response):
        try:
            os.remove(produced)
        except OSError:
            pass
        return response

    return send_file(produced, as_attachment=True, download_name=download_name)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
