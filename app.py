import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import FileResponse, JSONResponse

from models.schemas import WebhookPayload, JobResult, JobStatus
from services.queue import enqueue_job, job_store, start_workers


worker_tasks = []

API_KEYS = set()


def _load_api_keys():
    raw = os.environ.get("API_KEYS", "")
    if raw:
        for k in raw.split(","):
            k = k.strip()
            if k:
                API_KEYS.add(k)
    if not API_KEYS:
        print("[app] WARNING: No API_KEYS configured. Any X-Api-Key header will be accepted. Set API_KEYS env var (comma-separated) to restrict access.")


async def verify_api_key(x_api_key: str = Header(None)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key. Send your key in the X-Api-Key header.")
    if API_KEYS and x_api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return x_api_key


@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker_tasks
    _load_api_keys()
    print("[app] Starting background workers...")
    worker_tasks = await start_workers()
    yield
    print("[app] Shutting down workers...")
    for task in worker_tasks:
        task.cancel()
    await asyncio.gather(*worker_tasks, return_exceptions=True)


app = FastAPI(
    title="Vueling Refund Bot API",
    description="SaaS API for automating Vueling airline refund requests via webhook",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    return {
        "service": "Vueling Refund Bot API",
        "status": "running",
        "endpoints": {
            "POST /webhook": "Submit a new refund request",
            "GET /jobs": "List your jobs",
            "GET /jobs/{job_id}": "Get job status and result",
            "GET /jobs/{job_id}/screenshots": "List screenshots for a job",
            "GET /jobs/{job_id}/screenshots/{filename}": "Download a screenshot",
        },
    }


@app.post("/webhook", response_model=JobResult)
async def webhook_receive(payload: WebhookPayload, api_key: str = Depends(verify_api_key)):
    job = await enqueue_job(payload, api_key=api_key)
    return job


@app.get("/jobs")
async def list_jobs(api_key: str = Depends(verify_api_key)):
    jobs = job_store.list_by_api_key(api_key)
    return {
        "total": len(jobs),
        "jobs": [
            {
                "job_id": j.job_id,
                "status": j.status,
                "booking_code": j.booking_code,
                "claim_id": j.claim_id,
                "created_at": j.created_at,
                "case_number": j.case_number,
            }
            for j in jobs
        ],
    }


@app.get("/jobs/{job_id}", response_model=JobResult)
async def get_job(job_id: str, api_key: str = Depends(verify_api_key)):
    job = job_store.get(job_id)
    if not job or job.api_key != api_key:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/jobs/{job_id}/screenshots")
async def list_screenshots(job_id: str, api_key: str = Depends(verify_api_key)):
    job = job_store.get(job_id)
    if not job or job.api_key != api_key:
        raise HTTPException(status_code=404, detail="Job not found")

    screenshots_dir = os.path.join("screenshots", job_id)
    if not os.path.exists(screenshots_dir):
        return {"job_id": job_id, "screenshots": []}

    files = sorted(os.listdir(screenshots_dir))
    return {
        "job_id": job_id,
        "screenshots": [
            {"filename": f, "url": f"/jobs/{job_id}/screenshots/{f}"}
            for f in files
            if f.endswith(".png")
        ],
    }


@app.get("/jobs/{job_id}/screenshots/{filename}")
async def get_screenshot(job_id: str, filename: str, api_key: str = Depends(verify_api_key)):
    job = job_store.get(job_id)
    if not job or job.api_key != api_key:
        raise HTTPException(status_code=404, detail="Job not found")

    filepath = os.path.join("screenshots", job_id, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Screenshot not found")

    return FileResponse(filepath, media_type="image/png")


@app.get("/health")
async def health():
    return {"status": "healthy", "workers": 2}
