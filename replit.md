# Vueling Refund Bot

## Overview
A Python bot that automates the Vueling airline refund chatbot form. It navigates through the refund flow, fills in booking details, selects a cancellation reason, and optionally uploads medical documentation.

## Tech Stack
- Python 3.11
- Playwright (async) for browser automation
- playwright-stealth v2 for anti-bot detection
- System Chromium browser (headless or visible)

## Project Structure
- `main.py` - Main bot logic with `VuelingRefundBot` class, `BotStepError` exception, retry logic
- `config.py` - All configurable settings (booking code, email, delays, timeouts)
- `screenshots/` - Debug screenshots taken at each step
- `pyproject.toml` - Python dependencies

## How to Run
```bash
# Default: stops after selecting cancellation reason (step 7)
python main.py --headless

# Full flow including document upload
python main.py --headless --full-flow

# With custom arguments
python main.py --booking-code ABCDEF --email user@email.com --headless

# Visible browser (for debugging)
python main.py --no-headless
```

## Configuration
Settings are controlled via environment variables or `config.py`:
- `BOOKING_CODE` - Airline booking code (default: EHZRMC)
- `BOOKING_EMAIL` - Email used for booking (default: jimaesmith9871@gmail.com)
- `REFUND_REASON` - Cancellation reason (default: ILL OR HAVING SURGERY)
- `DOCUMENT_PATH` - Path to medical certificate
- `HEADLESS` - "true" or "false"

## Bot Flow
1. Launch Chromium browser with stealth settings
2. Navigate to Vueling refund page + dismiss cookie banner
3. Wait for chatbot widget to load (detects iframes)
4. Select "CODE AND EMAIL" lookup method
5. Fill booking code and email
6. Click SEND and wait for verification
7. Select cancellation reason (e.g., "ILL OR HAVING SURGERY")
8. **[Stops here by default]** - use `--full-flow` to continue
9. (Full flow) Confirm documents ready and upload medical certificate

## Error Handling
- Each step has retry logic (configurable retries per step)
- `BotStepError` custom exception tracks which step failed
- Screenshots captured at each step and on errors
- Structured result dict returned with success status, completed steps, and errors
- Bot returns result dict suitable for future FastAPI integration

## User Preferences
- Will convert to FastAPI later
- Stop after illness reason selection by default

## Recent Changes
- 2026-02-12: Added stop_after_reason flag, improved error handling with retries
- 2026-02-12: Updated default email to jimaesmith9871@gmail.com
- 2026-02-12: Initial project setup with Playwright automation
