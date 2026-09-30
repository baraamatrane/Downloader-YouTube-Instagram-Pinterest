"""Manually exercise one real download through the local API without a browser.

Usage: python smoke_test.py URL [mp3|mp4|image]
"""

import sys
import time

import app


def main() -> int:
    if len(sys.argv) not in {2, 3}:
        print("Usage: python smoke_test.py URL [mp3|mp4|image]")
        return 2

    media_format = sys.argv[2] if len(sys.argv) == 3 else "mp3"
    client = app.app.test_client()
    response = client.post("/api/download", json={"url": sys.argv[1], "format": media_format})
    if response.status_code != 202:
        print(response.json)
        return 1

    job_id = response.json["job_id"]
    last = None
    started = time.monotonic()
    while time.monotonic() - started < 120:
        job = client.get(f"/api/jobs/{job_id}").json
        current = (job["status"], job.get("progress"))
        if current != last:
            progress = f"{job['progress']}%" if job.get("progress") is not None else "..."
            print(f"{job['elapsed_seconds']:>3}s  {job['status']:<12} {progress:<6} {job.get('detail', '')}", flush=True)
            last = current
        if job["status"] == "ready":
            file_response = client.get(job["download_url"])
            print(f"Ready: {job['filename']} ({job['size']} bytes); HTTP {file_response.status_code}")
            file_response.close()
            return 0
        if job["status"] == "error":
            print(f"Failed: {job['error']}")
            return 1
        time.sleep(0.25)
    print("Timed out after 120 seconds")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
