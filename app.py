import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from models.schemas import WebhookPayload, JobResult, JobStatus, VerifyPayload, VerifyResult
from services.queue import enqueue_job, job_store, start_workers, enqueue_verify, verify_store


worker_tasks = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker_tasks
    try:
        print("[app] Starting background workers...")
        worker_tasks = await start_workers()
    except Exception as e:
        print(f"[app] Warning: Failed to start workers: {e}")
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "service": "Vueling Refund Bot API",
        "status": "running",
        "endpoints": {
            "POST /webhook": "Submit a new refund request",
            "POST /verify": "Verify a booking exists",
            "GET /jobs": "List all refund jobs",
            "GET /jobs/{job_id}": "Get refund job status and result",
            "GET /verify/{job_id}": "Get booking verification result",
        },
    }


@app.post("/webhook", response_model=JobResult)
async def webhook_receive(payload: WebhookPayload):
    job = await enqueue_job(payload)
    return job


@app.get("/jobs")
async def list_jobs():
    jobs = job_store.list_all()
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
async def get_job(job_id: str):
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/jobs/{job_id}/screenshots")
async def list_screenshots(job_id: str):
    job = job_store.get(job_id)
    if not job:
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
async def get_screenshot(job_id: str, filename: str):
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    filepath = os.path.join("screenshots", job_id, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Screenshot not found")

    return FileResponse(filepath, media_type="image/png")


@app.post("/verify", response_model=VerifyResult)
async def verify_booking(payload: VerifyPayload):
    job = await enqueue_verify(payload)
    return job


@app.get("/verify/{job_id}", response_model=VerifyResult)
async def get_verify(job_id: str):
    job = verify_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Verification job not found")
    return job


@app.get("/health")
async def health():
    return {"status": "healthy", "workers": 2}
