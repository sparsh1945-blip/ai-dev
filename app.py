import uuid
import threading
import time
 
from flask import Flask, request, render_template, send_file, jsonify, after_this_request
import yt_dlp
 
app = Flask(__name__)
 
DOWNLOAD_DIR = "/app/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
 
# Optional cookies file exported from a logged-in browser (Netscape format).
# Mount it into the container at this path to fix "Sign in to confirm you're
# not a bot" errors. See README notes for how to export one.
import logging
 
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ytdl")
 
COOKIES_FILE = os.environ.get("COOKIES_FILE_PATH", "/etc/secrets/cookies.txt")
 
# Fallback: if a base64-encoded cookies file is provided via env var,
# decode it to disk. Useful when Render's Secret File mounting isn't
# behaving as expected — env vars are simpler and always available.
_COOKIES_B64 = os.environ.get("COOKIES_B64")
if _COOKIES_B64 and not os.path.exists(COOKIES_FILE):
    import base64
    try:
        FALLBACK_COOKIES_PATH = "/app/cookies_from_env.txt"
        with open(FALLBACK_COOKIES_PATH, "wb") as f:
            f.write(base64.b64decode(_COOKIES_B64))
        COOKIES_FILE = FALLBACK_COOKIES_PATH
        logging.getLogger("ytdl").info("Loaded cookies from COOKIES_B64 env var.")
    except Exception as e:
        logging.getLogger("ytdl").warning(f"Failed to decode COOKIES_B64: {e}")
 
# Log at startup whether the cookies file is actually present and looks valid
if os.path.exists(COOKIES_FILE):
    try:
        with open(COOKIES_FILE, "r") as f:
            first_line = f.readline().strip()
            line_count = sum(1 for _ in f) + 1
        looks_valid = first_line.startswith("# Netscape HTTP Cookie File") or first_line.startswith("# HTTP Cookie File")
        logger.info(f"cookies.txt found at {COOKIES_FILE} ({line_count} lines). Valid Netscape header: {looks_valid}")
    except Exception as e:
        logger.warning(f"cookies.txt found but couldn't be read: {e}")
else:
    logger.warning(f"No cookies file found at {COOKIES_FILE} — running without authentication.")
 
 
def base_ydl_opts():
    opts = {
        "noplaylist": True,
        "quiet": True,
        # Try multiple player clients in order; some bypass the bot check
        # more reliably than others depending on YouTube's current rollout.
        "extractor_args": {"youtube": {"player_client": ["tv", "android", "web"]}},
        "http_headers": {
            "User-Agent": "com.google.android.youtube/19.29.37 (Linux; U; Android 11) gzip"
        },
    }
    if os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
        logger.info("Using cookies file for this request.")
    else:
        logger.info("No cookies file available for this request.")
    return opts
 
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
 
    ydl_opts = base_ydl_opts()
    ydl_opts["outtmpl"] = out_template
 
    if fmt == "mp3":
        ydl_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
    else:
        ydl_opts.update({
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
        })
 
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "download")
    except Exception as e:
        logger.error(f"yt-dlp failed for url={url}: {e}")
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
 
 
@app.route("/debug")
def debug():
    exists = os.path.exists(COOKIES_FILE)
    info = {
        "cookies_path": COOKIES_FILE,
        "cookies_found": exists,
        "source": "env_var_b64" if COOKIES_FILE.endswith("cookies_from_env.txt") else "secret_file",
    }
    if exists:
        try:
            with open(COOKIES_FILE, "r") as f:
                first_line = f.readline().strip()
                line_count = sum(1 for _ in f) + 1
            info["line_count"] = line_count
            info["valid_header"] = first_line.startswith("# Netscape HTTP Cookie File") or first_line.startswith("# HTTP Cookie File")
        except Exception as e:
            info["read_error"] = str(e)
    return jsonify(info)
 
 
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)