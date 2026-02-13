import os

VUELING_REFUND_URL = "https://www.vueling.com/en/we-are-vueling/contact/management?helpCenterFlow=RefundJustifiedReasons"

BOOKING_CODE = os.environ.get("BOOKING_CODE", "EHZRMC")
EMAIL = os.environ.get("BOOKING_EMAIL", "jimaesmith9871@gmail.com")
REASON = os.environ.get("REFUND_REASON", "ILL OR HAVING SURGERY")

HEADLESS = True

SCREENSHOTS_DIR = "screenshots"

MIN_DELAY = 1.5
MAX_DELAY = 3.5

STEP_TIMEOUT = 45000
PAGE_LOAD_TIMEOUT = 60000

API_HOST = "0.0.0.0"
API_PORT = 5000

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
