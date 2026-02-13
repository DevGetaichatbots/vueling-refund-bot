import os
import shutil
import asyncio
import aiohttp
from pathlib import Path

TEMP_BASE_DIR = "/tmp/vueling_jobs"
MAX_TOTAL_SIZE = 4 * 1024 * 1024  # 4MB
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".tiff", ".tif"}


async def download_files_for_job(job_id: str, documents: list) -> list[str]:
    job_dir = os.path.join(TEMP_BASE_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    downloaded = []
    total_size = 0

    async with aiohttp.ClientSession() as session:
        for doc in documents:
            url = doc.url
            filename = doc.filename

            ext = os.path.splitext(filename)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                print(f"  [warn] Skipping file with unsupported extension: {filename} ({ext})")
                continue

            if not url.startswith(("http://", "https://")):
                print(f"  [warn] Skipping non-HTTP URL: {url}")
                continue

            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        print(f"  [warn] Failed to download {filename}: HTTP {resp.status}")
                        continue

                    content = await resp.read()
                    file_size = len(content)

                    if total_size + file_size > MAX_TOTAL_SIZE:
                        print(f"  [warn] Skipping {filename}: would exceed 4MB total limit")
                        continue

                    total_size += file_size
                    file_path = os.path.join(job_dir, filename)
                    with open(file_path, "wb") as f:
                        f.write(content)

                    downloaded.append(file_path)
                    print(f"  [download] {filename} ({file_size} bytes) -> {file_path}")

            except Exception as e:
                print(f"  [error] Failed to download {filename}: {e}")
                continue

    return downloaded


def cleanup_job_files(job_id: str):
    job_dir = os.path.join(TEMP_BASE_DIR, job_id)
    if os.path.exists(job_dir):
        shutil.rmtree(job_dir, ignore_errors=True)
        print(f"  [cleanup] Removed temp files for job {job_id}")


def get_job_dir(job_id: str) -> str:
    return os.path.join(TEMP_BASE_DIR, job_id)
