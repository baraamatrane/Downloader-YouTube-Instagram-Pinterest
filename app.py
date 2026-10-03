from __future__ import annotations

import atexit
import os
import re
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

# The launcher installs dependencies here when Windows' venv bootstrap is unavailable.
LOCAL_PACKAGES = Path(__file__).resolve().parent / ".packages"
if LOCAL_PACKAGES.is_dir():
    sys.path.insert(0, str(LOCAL_PACKAGES))

import imageio_ffmpeg
import requests
from bs4 import BeautifulSoup
from flask import Flask, abort, jsonify, render_template, request, send_file
from yt_dlp import YoutubeDL


app = Flask(__name__)

RUNTIME_PARENT = Path(__file__).resolve().parent / ".runtime"
DOWNLOAD_ROOT = RUNTIME_PARENT / uuid.uuid4().hex
DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
MAX_BYTES = 1_500_000_000
ALLOWED_FORMATS = {"mp3", "mp4", "image"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}


def is_pinterest_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return host == "pin.it" or host == "pinterest.com" or host.endswith(".pinterest.com")


def update_job(job_id: str, **changes) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(changes)


def safe_name(value: str, fallback: str = "download") -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "", value).strip(" .")
    return value[:160] or fallback


def validate_url(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Enter a valid http:// or https:// URL.")
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        raise ValueError("Local network URLs are not allowed.")
    return value


def progress_hook(job_id: str):
    def hook(data: dict) -> None:
        if data.get("status") == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            downloaded = data.get("downloaded_bytes", 0)
            progress = round(downloaded * 100 / total, 1) if total else None
            update_job(
                job_id,
                status="downloading",
                progress=progress,
                detail="Receiving media bytes...",
                downloaded_bytes=downloaded,
                total_bytes=total,
                speed=data.get("_speed_str", "").strip(),
                eta=data.get("_eta_str", "").strip(),
            )
        elif data.get("status") == "finished":
            update_job(job_id, status="processing", progress=None, eta="")

    return hook


def find_output(folder: Path) -> Path:
    files = [path for path in folder.iterdir() if path.is_file() and not path.name.endswith((".part", ".ytdl"))]
    if not files:
        raise RuntimeError("The download finished but no media file was created.")
    return max(files, key=lambda path: path.stat().st_mtime)


def download_with_ytdlp(job_id: str, url: str, media_format: str, folder: Path) -> tuple[Path, str]:
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    common = {
        "outtmpl": str(folder / "%(title).150s [%(id)s].%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [progress_hook(job_id)],
        "postprocessor_hooks": [postprocessor_hook(job_id)],
        "ffmpeg_location": ffmpeg_path,
        "socket_timeout": 30,
        "retries": 3,
        "max_filesize": MAX_BYTES,
    }
    if shutil.which("node"):
        common["js_runtimes"] = {"node": {}}

    pinterest = is_pinterest_url(url)
    if media_format == "mp3":
        common.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
    elif media_format == "mp4":
        common.update({
            # Pinterest video pins often publish only a video HLS stream. The
            # old selector required a separate M4A stream and rejected these pins.
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo[ext=mp4]/bestvideo*/best[ext=mp4]/best" if pinterest else "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
        })
    else:
        common.update({"format": "best"})

    update_job(job_id, status="extracting", detail="Checking available audio and video formats...")
    try:
        with YoutubeDL(common) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title") or "download"
    except Exception as error:
        # Some Pinterest pins change between a video pin and an image/HLS pin
        # while the metadata request is in flight. Retry with the broadest
        # single-stream selector before surfacing an error to the user.
        if pinterest and media_format == "mp4" and "Requested format is not available" in str(error):
            retry_options = dict(common)
            retry_options["format"] = "bestvideo*/best"
            update_job(job_id, status="extracting", detail="Retrying with the pin’s available video stream...")
            with YoutubeDL(retry_options) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title") or "download"
        else:
            raise

    return find_output(folder), safe_name(title)


def postprocessor_hook(job_id: str):
    def hook(data: dict) -> None:
        if data.get("status") == "started":
            update_job(job_id, status="processing", progress=None, detail="Converting the downloaded media...")

    return hook


def image_from_page(url: str) -> tuple[str, str]:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; Droply/1.0)"}
    response = requests.get(url, headers=headers, timeout=30, stream=True, allow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type.startswith("image/"):
        return response.url, Path(urlparse(response.url).path).stem or "image"

    if "html" not in content_type:
        raise ValueError("This URL does not point to a supported image or media page.")

    html = response.content[:5_000_000]
    soup = BeautifulSoup(html, "html.parser")
    candidates = [
        soup.find("meta", property="og:image"),
        soup.find("meta", attrs={"name": "twitter:image"}),
        soup.find("meta", property="og:image:secure_url"),
    ]
    image_url = next((item.get("content") for item in candidates if item and item.get("content")), None)
    title_tag = soup.find("meta", property="og:title") or soup.find("title")
    title = title_tag.get("content") if title_tag and title_tag.get("content") else title_tag.get_text() if title_tag else "image"
    if not image_url:
        raise ValueError("No downloadable image was found on that page.")
    return urljoin(response.url, image_url), safe_name(title, "image")


def download_image(url: str, folder: Path) -> tuple[Path, str]:
    image_url, title = image_from_page(url)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; Droply/1.0)", "Referer": url}
    with requests.get(image_url, headers=headers, timeout=60, stream=True) as response:
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if not content_type.startswith("image/"):
            raise ValueError("The page image is not available as a direct download.")
        extension = Path(urlparse(response.url).path).suffix.lower()
        if extension not in IMAGE_EXTENSIONS:
            extension = ".jpg" if content_type == "image/jpeg" else f".{content_type.split('/')[-1]}"
        output = folder / f"{safe_name(title, 'image')}{extension}"
        size = 0
        with output.open("wb") as file:
            for chunk in response.iter_content(1024 * 256):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("The file is larger than the 1.5 GB safety limit.")
                file.write(chunk)
    return output, title


def run_download(job_id: str, url: str, media_format: str) -> None:
    folder = DOWNLOAD_ROOT / job_id
    try:
        update_job(job_id, status="starting", detail="Creating the download workspace...")
        folder.mkdir(parents=True, exist_ok=True)
        if media_format == "image":
            update_job(job_id, status="extracting", detail="Finding the original image...")
            file_path, title = download_image(url, folder)
        else:
            file_path, title = download_with_ytdlp(job_id, url, media_format, folder)
        update_job(
            job_id,
            status="ready",
            progress=100,
            title=title,
            filename=file_path.name,
            path=str(file_path),
            size=file_path.stat().st_size,
            download_url=f"/api/files/{job_id}",
        )
    except Exception as error:
        message = str(error).splitlines()[-1]
        message = re.sub(r"^ERROR:\s*", "", message)
        update_job(job_id, status="error", error=message[:500] or "Download failed.")


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/download")
def create_download():
    data = request.get_json(silent=True) or {}
    try:
        url = validate_url(str(data.get("url", "")))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    media_format = str(data.get("format", "mp4")).lower()
    if media_format not in ALLOWED_FORMATS:
        return jsonify(error="Choose MP3, MP4, or original image."), 400

    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "status": "queued",
            "progress": None,
            "created_at": time.time(),
            "format": media_format,
        }
    threading.Thread(target=run_download, args=(job_id, url, media_format), daemon=True).start()
    return jsonify(job_id=job_id), 202


@app.get("/api/jobs/<job_id>")
def job_status(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            abort(404)
        public_job = {key: value for key, value in job.items() if key not in {"path", "created_at"}}
        public_job["elapsed_seconds"] = round(time.time() - job["created_at"])
    return jsonify(public_job)


@app.get("/api/files/<job_id>")
def get_file(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job or job.get("status") != "ready":
            abort(404)
        path = Path(job["path"])
        filename = job["filename"]
    if not path.is_file() or path.parent != DOWNLOAD_ROOT / job_id:
        abort(404)
    return send_file(path, as_attachment=True, download_name=filename)


@app.get("/api/health")
def health():
    return jsonify(ok=True)


@atexit.register
def clean_temp_files() -> None:
    shutil.rmtree(DOWNLOAD_ROOT, ignore_errors=True)
    try:
        RUNTIME_PARENT.rmdir()
    except OSError:
        pass


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("DROPLY_PORT", "5000")), debug=False, threaded=True)
