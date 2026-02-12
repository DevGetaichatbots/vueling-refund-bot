# Vueling Refund Bot

## Overview
A Python bot that automates the Vueling airline refund chatbot form. It navigates through the refund flow, fills in booking details, selects a cancellation reason, and uploads medical documentation.

## Tech Stack
- Python 3.11
- Playwright (async) for browser automation
- playwright-stealth for anti-bot detection
- Chromium browser (headless or visible)

## Project Structure
- `main.py` - Main bot logic with `VuelingRefundBot` class
- `config.py` - All configurable settings (booking code, email, delays, timeouts)
- `screenshots/` - Debug screenshots taken at each step
- `pyproject.toml` - Python dependencies

## How to Run
```bash
# Default (uses config.py values)
python main.py

# With custom arguments
python main.py --booking-code EHZRMC --email user@email.com --document medical.pdf

# Headless mode
python main.py --headless

# Visible browser (for debugging)
python main.py --no-headless
```

## Configuration
Settings are controlled via environment variables or `config.py`:
- `BOOKING_CODE` - Airline booking code
- `BOOKING_EMAIL` - Email used for booking
- `REFUND_REASON` - Cancellation reason
- `DOCUMENT_PATH` - Path to medical certificate
- `HEADLESS` - "true" or "false"

## Bot Flow
1. Launch Chromium browser with stealth settings
2. Navigate to Vueling refund page
3. Wait for chatbot widget to load
4. Select "CODE AND EMAIL" lookup method
5. Fill booking code and email
6. Click SEND and wait for verification
7. Select cancellation reason (e.g., "ILL OR HAVING SURGERY")
8. Confirm documents ready and upload medical certificate
9. Take confirmation screenshot

## Recent Changes
- 2026-02-12: Initial project setup with Playwright automation
