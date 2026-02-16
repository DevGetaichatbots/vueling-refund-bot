import asyncio
import os
import shutil
import time
import traceback
from typing import Optional

from models.schemas import WebhookPayload, JobResult, JobStatus, create_job
from services.bot import VuelingRefundBot
from utils.downloads import download_files_for_job, cleanup_job_files
import config


class JobStore:
    def __init__(self):
        self._jobs: dict[str, JobResult] = {}
        self._payloads: dict[str, WebhookPayload] = {}
        self._lock = asyncio.Lock()

    async def add(self, job: JobResult, payload: WebhookPayload):
        async with self._lock:
            self._jobs[job.job_id] = job
            self._payloads[job.job_id] = payload

    def get(self, job_id: str) -> Optional[JobResult]:
        return self._jobs.get(job_id)

    def get_payload(self, job_id: str) -> Optional[WebhookPayload]:
        return self._payloads.get(job_id)

    async def update(self, job_id: str, **kwargs):
        async with self._lock:
            job = self._jobs.get(job_id)
            if job:
                for k, v in kwargs.items():
                    setattr(job, k, v)

    def list_all(self) -> list[JobResult]:
        return list(self._jobs.values())


job_store = JobStore()
job_queue: asyncio.Queue = asyncio.Queue()

MAX_CONCURRENT_WORKERS = 2


async def enqueue_job(payload: WebhookPayload) -> JobResult:
    job = create_job(payload)
    await job_store.add(job, payload)
    await job_queue.put(job.job_id)
    print(f"[queue] Job {job.job_id} queued for {payload.booking_code}")
    return job


async def process_job(job_id: str):
    job = job_store.get(job_id)
    payload = job_store.get_payload(job_id)
    if not job or not payload:
        return

    await job_store.update(job_id, status=JobStatus.RUNNING, started_at=time.time())
    print(f"\n[worker] Starting job {job_id} for booking {payload.booking_code}")

    downloaded_files = []
    try:
        if payload.documents:
            print(f"[worker] Downloading {len(payload.documents)} document(s)...")
            downloaded_files = await download_files_for_job(job_id, payload.documents)
            print(f"[worker] Downloaded {len(downloaded_files)} file(s)")

        async def on_progress(completed_steps=None, errors=None, screenshots=None, case_number=None):
            updates = {}
            if completed_steps is not None:
                updates["completed_steps"] = completed_steps
            if errors is not None:
                updates["errors"] = errors
            if screenshots is not None:
                updates["screenshots"] = screenshots
            if case_number is not None:
                updates["case_number"] = case_number
            if updates:
                await job_store.update(job_id, **updates)

        bot = VuelingRefundBot(
            booking_code=payload.booking_code,
            email=payload.booking_email,
            reason=payload.reason.value,
            first_name=payload.first_name,
            surname=payload.surname,
            contact_email=payload.contact_email,
            phone_prefix=payload.resolved_phone_prefix,
            phone_number=payload.resolved_phone_number,
            comment=payload.comment,
            document_paths=downloaded_files,
            headless=True,
            job_id=job_id,
            on_progress=on_progress,
            callback_url=payload.callback_url,
            claim_id=payload.claim_id,
        )

        result = await bot.run()

        await job_store.update(
            job_id,
            status=JobStatus.COMPLETED if result["success"] else JobStatus.FAILED,
            completed_at=time.time(),
            completed_steps=result.get("completed_steps", []),
            case_number=result.get("case_number"),
            errors=result.get("errors", []),
            screenshots=result.get("screenshots", []),
        )

        status = "completed" if result["success"] else "failed"
        print(f"[worker] Job {job_id} {status}")

    except Exception as e:
        print(f"[worker] Job {job_id} crashed: {e}")
        traceback.print_exc()
        await job_store.update(
            job_id,
            status=JobStatus.FAILED,
            completed_at=time.time(),
            errors=[{"step": "worker", "error": str(e)}],
        )

    finally:
        cleanup_job_files(job_id)
        screenshots_dir = os.path.join(config.SCREENSHOTS_DIR, job_id)
        if os.path.exists(screenshots_dir):
            shutil.rmtree(screenshots_dir, ignore_errors=True)
            print(f"  [cleanup] Removed screenshots for job {job_id}")


async def worker(worker_id: int):
    print(f"[worker-{worker_id}] Started")
    while True:
        try:
            job_id = await job_queue.get()
            await process_job(job_id)
            job_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[worker-{worker_id}] Unexpected error: {e}")
            traceback.print_exc()


async def start_workers():
    tasks = []
    for i in range(MAX_CONCURRENT_WORKERS):
        task = asyncio.create_task(worker(i))
        tasks.append(task)
    return tasks
