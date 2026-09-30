import shutil
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import app as droply


class DroplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(__file__).parent / ".runtime" / uuid.uuid4().hex
        self.temp.mkdir(parents=True)
        self.root_patch = patch.object(droply, "DOWNLOAD_ROOT", self.temp)
        self.root_patch.start()
        self.client = droply.app.test_client()

    def tearDown(self):
        self.root_patch.stop()
        shutil.rmtree(self.temp, ignore_errors=True)
        with droply.JOBS_LOCK:
            droply.JOBS.clear()

    def test_home_and_health(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/api/health").json, {"ok": True})

    def test_rejects_invalid_input(self):
        response = self.client.post("/api/download", json={"url": "not a url", "format": "mp4"})
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/download", json={"url": "https://example.com", "format": "exe"})
        self.assertEqual(response.status_code, 400)

    def test_background_job_becomes_downloadable(self):
        def fake_image_download(_url, folder):
            output = folder / "Sample image.png"
            output.write_bytes(b"fake-png-content")
            return output, "Sample image"

        with patch.object(droply, "download_image", side_effect=fake_image_download):
            response = self.client.post(
                "/api/download",
                json={"url": "https://example.com/image", "format": "image"},
            )
            self.assertEqual(response.status_code, 202)
            job_id = response.json["job_id"]

            job = None
            for _ in range(100):
                job = self.client.get(f"/api/jobs/{job_id}").json
                if job["status"] in {"ready", "error"}:
                    break
                time.sleep(0.01)

            self.assertEqual(job["status"], "ready")
            self.assertNotIn("path", job)
            file_response = self.client.get(job["download_url"])
            self.assertEqual(file_response.status_code, 200)
            self.assertEqual(file_response.data, b"fake-png-content")
            self.assertIn("attachment", file_response.headers["Content-Disposition"])
            file_response.close()


if __name__ == "__main__":
    unittest.main()
