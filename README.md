# Droply

A private, local web interface for saving permitted media from supported URLs as MP4, MP3, or an original image.

## Start

Right-click `run.ps1` and choose **Run with PowerShell**, or open PowerShell in this folder and run:

```powershell
.\run.ps1
```

The first launch installs the required packages into a private `.packages` folder inside this project. Your browser then opens to <http://127.0.0.1:5000>.

## Notes

- The app only listens on your computer (`127.0.0.1`).
- Temporary downloads are removed when the server stops.
- Some private, age-restricted, or login-only media cannot be accessed without authentication.
- Platform changes can occasionally require updating `yt-dlp`.
- YouTube downloads use the bundled `yt-dlp-ejs` solver and require Node.js 22 or newer on your PATH.
- Only download content you own or have permission to use, and follow the source platform's terms.
