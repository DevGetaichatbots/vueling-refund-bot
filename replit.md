# Vueling Refund Bot - SaaS API

## Overview
A FastAPI-based SaaS application that automates Vueling airline refund chatbot requests and booking verification. External systems send refund requests via webhook, and background workers process them using Playwright browser automation with stealth detection. A separate booking verification endpoint checks if tickets exist and extracts flight details.

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
│   ├── verify_bot.py       # BookingVerifyBot class (booking verification)
│   └── queue.py            # Async job queue + worker pool (refund + verify)
├── utils/
│   ├── downloads.py        # File download + temp storage management
│   └── browser_env.py      # Dynamic library path setup for Playwright
├── screenshots/            # Per-job screenshot folders
└── pyproject.toml          # Python dependencies
```

## API Endpoints
- `POST /webhook` - Submit a refund request (returns job_id)
- `GET /jobs` - List all jobs
- `GET /jobs/{job_id}` - Get job status, completed steps, case number
- `GET /jobs/{job_id}/screenshots` - List screenshots for a job
- `GET /jobs/{job_id}/screenshots/{filename}` - Download a screenshot
- `POST /verify` - Submit booking verification request (returns job_id)
- `GET /verify/{job_id}` - Get verification result (verified, booking_details)
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
  "phone_country_code": "ES",
  "phone_prefix": "+34",
  "phone_number": "612345678",
  "comment": "Medical emergency",
  "documents": [
    {"url": "https://example.com/cert.pdf", "filename": "cert.pdf"}
  ],
  "claim_id": "your-internal-claim-id",
  "callback_url": "https://your-app.com/api/v1/claims/bot-status-update"
}
```
- `phone_country_code`: Country code (e.g. "ES", "US", "GB") - OPTIONAL
- `phone_prefix`: International dialing prefix (e.g. "+34", "+1") - pre-parsed from frontend
- `phone_number`: Digits only, no prefix (e.g. "612345678")
- `phone_country`: DEPRECATED - old combined prefix field, still accepted for backward compatibility
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

## Deployment
- Type: Reserved VM (0.5 vCPU / 2 GiB RAM)
- Build: `pip install -r requirements.txt && rm -f .pythonlibs/.../playwright/driver/node` (removes 116MB node binary from bundle)
- Run: `bash start.sh` (restores node driver + installs Playwright browser on first startup, then starts server)
- Browsers stored at `/tmp/pw-browsers/` via PLAYWRIGHT_BROWSERS_PATH env var (outside workspace, NOT bundled)
- Total deploy bundle: ~62MB (vs 440MB+ with browsers + node bundled)
- First deploy startup: ~30-60s extra to download Node.js driver + headless shell
- Subsequent restarts: instant (driver + browser already in place on VM)

## Booking Verification
`POST /verify` accepts:
```json
{
  "booking_code": "CJ6PKJ",
  "booking_email": "jimaesmith9871@gmail.com",
  "claim_id": "optional-internal-id",
  "callback_url": "https://your-app.com/api/v1/claims/verify-callback"
}
```
Response from `GET /verify/{job_id}`:
```json
{
  "verified": true,
  "booking_details": {
    "booking_code": "CJ6PKJ",
    "exists": true,
    "flights": [
      {
        "flight_date": "28.01.2026",
        "direction": "outbound",
        "origin_city": "Barcelona",
        "destination_city": "Lisbon",
        "origin": "BCN",
        "destination": "LIS",
        "origin_terminal": "BCN (T1)",
        "destination_terminal": "LIS (T2)",
        "departure_time": "15:50",
        "arrival_time": "16:55",
        "flight_number": "VY8466"
      }
    ],
    "passengers": 1
  }
}
```
- Bot navigates to Vueling booking retrieval page, fills code + email, clicks Go
- Extracts all flight segments (outbound + return), cities, airports, terminals, times, flight numbers
- Sends callback with verification result when `callback_url` provided
- Uses separate queue worker (1 concurrent) independent from refund queue

## Recent Changes
- 2026-02-17: Added booking verification bot (POST /verify) - navigates to Vueling booking retrieval page, fills code + email, extracts full flight details (cities, airports, terminals, times, flight numbers, passengers). Supports multiple flight segments (outbound + return). Uses correct page selectors (CONFIRMATIONNUMBER, CONTACTEMAIL, LinkButtonRetrieve, flightDetailsBox CSS classes).
- 2026-02-17: Fixed deployment timeout - moved Playwright browser install from build to runtime startup via start.sh. Set PLAYWRIGHT_BROWSERS_PATH=/tmp/pw-browsers to store browsers outside workspace (not bundled). Reduced bundle from 440MB to 182MB. Added --single-process and --disable-setuid-sandbox launch flags.
- 2026-02-16: Fixed Step 7 (YES button) - chatbot sends 6+ messages after reason selection before showing YES/NO buttons. Added extended wait in Step 6 to detect document prompt text before proceeding. Rewrote Step 7 with 30s polling loop, scrolling to bottom, multiple selectors (button, div[role=button], span, class*=button), scrollIntoView, force-click fallback. All SEND/SUBMIT buttons now raise exceptions on failure to trigger retries instead of silently continuing.
- 2026-02-16: Fixed deployment timeout - lazy import of playwright (133MB) so app starts in <1s and passes health check. Cleaned cache/attached_assets to reduce bundle size.
- 2026-02-16: Updated phone number handling - now accepts pre-parsed fields (phone_country_code, phone_prefix, phone_number) from frontend. Bot uses exact prefix for dropdown selection, no more parsing/guessing. Old format (phone_country) still supported for backward compatibility.
- 2026-02-16: Removed API key authentication per user request - endpoints are open
- 2026-02-16: Added real-time status callback system - bot POSTs progress updates to callback_url at each step with claimId, step name, message, progress %, and status
- 2026-02-13: Improved bot reliability - new smart waiting system that tracks chatbot message count before/after each action, waits for responses to stabilize before proceeding, and expects specific UI elements at each step (input fields, dropdowns, file upload). Increased timeouts (phone dropdown 5s→15s, step timeout 30s→45s). Bot now properly waits for chatbot response after every input before moving to next step.
- 2026-02-13: Added all 4 refund reasons, document upload confirmation ("Yes, continue"), improved case/reference number extraction
- 2026-02-13: Added PREGNANT reason, made comment optional, fixed phone country dropdown selection, improved file upload with "Select them" button
- 2026-02-13: Converted to FastAPI SaaS with webhook, job queue, and full 14-step chatbot flow
- 2026-02-12: Initial CLI bot setup with Playwright
