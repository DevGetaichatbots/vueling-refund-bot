# ✈️ AI Airline Vueling Refund Automation Bot

> A production-ready SaaS API that automates Vueling airline refund requests and booking verification using AI-powered browser automation — no manual form filling required.

[![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.129-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![Playwright](https://img.shields.io/badge/Playwright-1.58-orange?logo=playwright)](https://playwright.dev)
[![Railway](https://img.shields.io/badge/Deploy-Railway-purple?logo=railway)](https://railway.app)

---

## 🚀 What It Does

This bot automates the entire Vueling airline refund process end-to-end:

- **Refund Bot** — receives a webhook with passenger details, opens the Vueling chatbot in a headless browser, navigates all 14 steps automatically (booking lookup → reason selection → passenger details → document upload → case number extraction), and sends real-time progress callbacks to your frontend.
- **Booking Verifier** — synchronously checks if a booking exists and returns full flight details (routes, times, airports, terminals, flight numbers) in ~20 seconds.

---

## 🏗️ Architecture

```
External App
     │
     ▼
POST /webhook ──► Job Queue (2 workers) ──► VuelingRefundBot (Playwright)
     │                                            │
     │                                    14-step chatbot flow
     │                                            │
     ▼                                            ▼
GET /jobs/{id}                          Callback URL (real-time progress)

POST /verify ──► BookingVerifyBot (Playwright) ──► Returns JSON result (~20s)
```

**Stack:**
- **FastAPI + Uvicorn** — async HTTP server
- **Playwright (async)** — headless Chromium browser automation
- **playwright-stealth** — anti-bot detection bypass
- **aiohttp** — downloads documents from webhook URLs
- **In-memory job store** — no database needed

---

## 📁 Project Structure

```
├── main.py                  # Entry point (Uvicorn)
├── app.py                   # FastAPI routes + lifespan
├── config.py                # Global settings (timeouts, delays, URLs)
├── Dockerfile               # Docker image for Railway deployment
├── railway.toml             # Railway deployment config
├── requirements.txt         # Python dependencies
├── models/
│   └── schemas.py           # Pydantic models (WebhookPayload, JobResult)
├── services/
│   ├── bot.py               # VuelingRefundBot — 14-step chatbot automation
│   ├── verify_bot.py        # BookingVerifyBot — booking lookup & flight extraction
│   └── queue.py             # Async job queue + worker pool
├── utils/
│   ├── downloads.py         # Document downloader + temp file cleanup
│   └── browser_env.py       # Dynamic library path setup (Replit env)
└── screenshots/             # Per-job screenshots (auto-cleaned after job)
```

---

## 🔌 API Reference

### `POST /webhook` — Submit Refund Request

Queues a new refund job and returns a `job_id` immediately.

**Request body:**
```json
{
  "booking_code": "CJ6PKJ",
  "booking_email": "passenger@example.com",
  "reason": "ILL OR HAVING SURGERY",
  "first_name": "John",
  "surname": "Smith",
  "contact_email": "john@example.com",
  "phone_country_code": "ES",
  "phone_prefix": "+34",
  "phone_number": "612345678",
  "comment": "Medical emergency",
  "documents": [
    { "url": "https://example.com/medical-cert.pdf", "filename": "cert.pdf" }
  ],
  "claim_id": "your-internal-id",
  "callback_url": "https://your-app.com/api/bot-status"
}
```

**Supported reasons:**
| Value | Description |
|-------|-------------|
| `ILL OR HAVING SURGERY` | Medical condition or surgery |
| `PREGNANT` | Pregnancy |
| `COURT SUMMONS OR SERVICE AT POLLING STATION` | Legal obligation |
| `SOMEONE'S DEATH` | Bereavement |

**Response:**
```json
{ "job_id": "abc-123", "status": "queued", "booking_code": "CJ6PKJ" }
```

---

### `GET /jobs/{job_id}` — Poll Job Status

```json
{
  "job_id": "abc-123",
  "status": "completed",
  "booking_code": "CJ6PKJ",
  "case_number": "VY-2026-88451",
  "completed_steps": ["Launch Browser", "Navigate", "..."],
  "rejected": false,
  "rejection_reason": null
}
```

**Status values:**

| Status | Meaning |
|--------|---------|
| `queued` | Waiting for an available worker |
| `running` | Bot is actively filling the form |
| `completed` | Refund submitted — `case_number` available |
| `failed` | Error occurred (retried automatically) |
| `rejected` | Airline refused the refund — `rejection_reason` explains why |

---

### `POST /verify` — Verify Booking (Synchronous)

Checks if a booking exists and returns full flight details. Waits ~20s for result.

**Request:**
```json
{
  "booking_code": "CJ6PKJ",
  "booking_email": "passenger@example.com",
  "claim_id": "optional-id",
  "callback_url": "https://your-app.com/api/verify-callback"
}
```

**Response (found):**
```json
{
  "verified": true,
  "booking_code": "CJ6PKJ",
  "booking_details": {
    "booking_code": "CJ6PKJ",
    "exists": true,
    "passengers": 1,
    "flights": [
      {
        "direction": "outbound",
        "flight_date": "28.01.2026",
        "flight_number": "VY8466",
        "origin_city": "Barcelona",
        "destination_city": "Lisbon",
        "origin": "BCN",
        "destination": "LIS",
        "origin_terminal": "BCN (T1)",
        "destination_terminal": "LIS (T2)",
        "departure_time": "15:50",
        "arrival_time": "16:55"
      }
    ]
  }
}
```

**Response (not found):**
```json
{ "verified": false, "booking_code": "CJ6PKJ", "error": "Booking not found or invalid credentials" }
```

---

### `GET /jobs` — List All Jobs

Returns all queued/running/completed jobs in memory.

### `GET /health` — Health Check

```json
{ "status": "healthy", "workers": 2 }
```

---

## 📡 Real-Time Callbacks

When `callback_url` is provided, the bot POSTs progress updates at every step:

```json
{
  "claimId": "your-internal-id",
  "step": "uploading_documents",
  "message": "Uploading supporting documents",
  "progress": 70,
  "status": "in_progress"
}
```

**Progress flow:**

| Step key | Progress | Description |
|----------|----------|-------------|
| `navigating_to_portal` | 5–15% | Opening airline refund portal |
| `entering_booking` | 20–25% | Entering booking reference |
| `selecting_refund_type` | 30% | Selecting refund reason |
| `filling_passenger` | 35–50% | Filling passenger details |
| `submitting_claim` | 60–85% | Submitting the claim |
| `uploading_documents` | 70% | Uploading documents |
| `completed` | 100% | Refund submitted successfully |
| `error` | — | Bot encountered an unrecoverable error |
| `rejected` | — | Airline refused the refund |

---

## 🤖 The 14-Step Bot Flow

| Step | Action |
|------|--------|
| 1 | Launch Chromium with stealth (anti-bot bypass) |
| 2 | Navigate to Vueling refund page + dismiss cookies |
| 3 | Wait for chatbot widget to load |
| 4 | Select **CODE AND EMAIL** lookup method |
| 5 | Fill booking code + email → click SEND |
| 6 | Select cancellation reason |
| 7 | Confirm documents ready → click YES |
| 8 | Fill first name + surname → click SEND |
| 9 | Type contact email in chat |
| 10 | Select phone country prefix + fill number → click SEND |
| 11 | Submit optional comment → click SUBMIT QUERY |
| 12 | Upload documents via file picker → click "Yes, continue" |
| 13 | Extract case/reference number from confirmation |
| 14 | Decline another refund → click NO |

---

## 🚢 Deployment (Railway)

### One-click deploy from GitHub:

1. Fork or push this repo to your GitHub account
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
3. Select this repository — Railway auto-detects the `Dockerfile`
4. Set environment variable: `PORT=8080` (Railway sets this automatically)
5. Health check is configured at `/health` with a 120s timeout

### Docker build process:
```dockerfile
FROM python:3.11-slim
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN pip install -r requirements.txt
RUN playwright install --with-deps   # installs Chromium + all system deps
```

### Resource requirements:
- Minimum **512MB RAM** (Chromium needs memory)
- Recommended **1 vCPU** for smooth concurrent job processing
- 2 concurrent refund workers by default (`MAX_CONCURRENT_WORKERS = 2`)

---

## 💻 Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Run the server
python main.py
# Server starts on http://0.0.0.0:5000
```

**Test the verify endpoint:**
```bash
curl -X POST http://localhost:5000/verify \
  -H "Content-Type: application/json" \
  -d '{"booking_code": "CJ6PKJ", "booking_email": "your@email.com"}'
```

**Submit a refund request:**
```bash
curl -X POST http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "booking_code": "CJ6PKJ",
    "booking_email": "your@email.com",
    "reason": "ILL OR HAVING SURGERY",
    "first_name": "John",
    "surname": "Smith",
    "contact_email": "john@email.com",
    "phone_prefix": "+34",
    "phone_number": "612345678"
  }'
```

---

## 🔒 Key Design Decisions

| Decision | Reason |
|----------|--------|
| No database | Jobs stored in memory — simple, fast, no external dependencies |
| Synchronous `/verify` | Frontend shows a loading spinner; 20s wait is acceptable for UX |
| Rejection != failure | When airline rejects (e.g. past 30-day window), bot stops immediately — no pointless retries |
| stealth plugin | Vueling's chatbot detects automation; stealth bypasses fingerprinting |
| `--with-deps` install | Playwright headless shell requires system libraries not in slim Docker images |

---

## 📝 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `5000` | HTTP server port |
| `PLAYWRIGHT_BROWSERS_PATH` | `/ms-playwright` | Where Playwright stores browser binaries |

---

## 📄 License

MIT — feel free to use, modify, and deploy.
