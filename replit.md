# Vueling Refund Bot - SaaS API

## Overview
A FastAPI-based SaaS application that automates Vueling airline refund chatbot requests. External systems send refund requests via webhook, and background workers process them using Playwright browser automation with stealth detection.

## Tech Stack
- Python 3.11
- FastAPI + Uvicorn (API server on port 5000)
- Playwright (async) for browser automation
- playwright-stealth v2 for anti-bot detection
- aiohttp for downloading documents from webhook URLs
- System Chromium browser (headless)

## Project Structure
```
├── main.py                 # Entry point - starts Uvicorn server
├── app.py                  # FastAPI app with webhook + job endpoints
├── config.py               # Global settings (delays, timeouts, URLs)
├── models/
│   └── schemas.py          # Pydantic models (WebhookPayload, JobResult)
├── services/
│   ├── bot.py              # VuelingRefundBot class (14-step chatbot flow)
│   └── queue.py            # Async job queue + worker pool
├── utils/
│   └── downloads.py        # File download + temp storage management
├── screenshots/            # Per-job screenshot folders
└── pyproject.toml          # Python dependencies
```

## API Endpoints
- `POST /webhook` - Submit a refund request (returns job_id)
- `GET /jobs` - List all jobs
- `GET /jobs/{job_id}` - Get job status, completed steps, case number
- `GET /jobs/{job_id}/screenshots` - List screenshots for a job
- `GET /jobs/{job_id}/screenshots/{filename}` - Download a screenshot
- `GET /health` - Health check

## Webhook Payload
```json
{
  "booking_code": "CJ6PKJ",
  "booking_email": "jimaesmith9871@gmail.com",
  "reason": "ILL OR HAVING SURGERY",
  "first_name": "John",
  "surname": "Smith",
  "contact_email": "jamiesmith@gmail.com",
  "phone_country": "+92",
  "phone_number": "3176811061",
  "comment": "Medical emergency",
  "documents": [
    {"url": "https://example.com/cert.pdf", "filename": "cert.pdf"}
  ],
  "claim_id": "your-internal-claim-id",
  "callback_url": "https://your-app.com/api/v1/claims/bot-status-update"
}
```
- `reason`: "ILL OR HAVING SURGERY", "PREGNANT", "COURT SUMMONS OR SERVICE AT POLLING STATION", or "SOMEONE'S DEATH"
- `comment`: OPTIONAL - can be omitted or null
- `claim_id`: OPTIONAL - your internal claim ID for status callbacks (falls back to job_id)
- `callback_url`: OPTIONAL - URL to receive real-time step progress POST updates

## Bot Flow (14 Steps)
1. Launch Chromium browser with stealth
2. Navigate to Vueling refund page + dismiss cookies
3. Wait for chatbot widget to load
4. Select "CODE AND EMAIL" lookup method
5. Fill booking code + email → SEND
6. Select cancellation reason ("ILL OR HAVING SURGERY", "PREGNANT", "COURT SUMMONS OR SERVICE AT POLLING STATION", "SOMEONE'S DEATH")
7. Confirm documents ready → YES
8. Fill first name + surname → SEND
9. Type contact email in chat
10. Select phone country prefix from dropdown + fill number → SEND
11. Submit optional comment (or just click SUBMIT QUERY if none) → SUBMIT QUERY
12. Upload documents via "Select them" button (PDF/JPG/PNG/GIF/TIFF, max 4MB) → click "Yes, continue"
13. Extract case/reference number from confirmation
14. Decline another refund → NO

## Multi-User Architecture
- Async job queue with 2 concurrent workers
- Each job gets a unique ID and isolated temp file storage
- Documents downloaded from webhook URLs to `/tmp/vueling_jobs/{job_id}/`
- Files cleaned up automatically after job completes
- Screenshots stored per-job in `screenshots/{job_id}/`

## User Preferences
- Default email: jimaesmith9871@gmail.com
- Refund reasons supported: "ILL OR HAVING SURGERY", "PREGNANT", "COURT SUMMONS OR SERVICE AT POLLING STATION", "SOMEONE'S DEATH"
- Comment field is optional - bot clicks Submit Query regardless

## Callback Status Updates
When `callback_url` is provided in the webhook, the bot POSTs progress updates at each step:
```json
{"claimId": "...", "step": "navigating_to_portal", "message": "Opening airline refund portal", "progress": 10, "status": "in_progress"}
```
Steps in order: navigating_to_portal (5-15%) → entering_booking (20-25%) → selecting_refund_type (30%) → filling_passenger (35-50%) → submitting_claim (60%) → uploading_documents (70%) → submitting_claim (85%) → completed (100%)
On error: `{"step": "error", "status": "error", "message": "...", "progress": <last_progress>}`

## Recent Changes
- 2026-02-16: Added real-time status callback system - bot POSTs progress updates to callback_url at each step with claimId, step name, message, progress %, and status
- 2026-02-13: Improved bot reliability - new smart waiting system that tracks chatbot message count before/after each action, waits for responses to stabilize before proceeding, and expects specific UI elements at each step (input fields, dropdowns, file upload). Increased timeouts (phone dropdown 5s→15s, step timeout 30s→45s). Bot now properly waits for chatbot response after every input before moving to next step.
- 2026-02-13: Added all 4 refund reasons, document upload confirmation ("Yes, continue"), improved case/reference number extraction
- 2026-02-13: Added PREGNANT reason, made comment optional, fixed phone country dropdown selection, improved file upload with "Select them" button
- 2026-02-13: Converted to FastAPI SaaS with webhook, job queue, and full 14-step chatbot flow
- 2026-02-12: Initial CLI bot setup with Playwright
