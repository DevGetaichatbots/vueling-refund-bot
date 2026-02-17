import asyncio
import shutil
import traceback

import aiohttp
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

import config

VERIFY_URL = "https://tickets.vueling.com/RetrieveBooking.aspx?event=change&culture=en-GB"


class BookingVerifyBot:
    def __init__(self, booking_code, email, job_id=None, callback_url=None, claim_id=None):
        self.booking_code = booking_code
        self.email = email
        self.job_id = job_id or "verify"
        self.callback_url = callback_url
        self.claim_id = claim_id
        self.browser = None
        self.page = None
        self.playwright = None
        self.pw_cm = None
        self.stealth = None

    async def send_callback(self, verified, booking_details=None, error=None):
        if not self.callback_url:
            return
        payload = {
            "claimId": self.claim_id or self.job_id,
            "type": "booking_verification",
            "verified": verified,
            "booking_code": self.booking_code,
            "booking_email": self.email,
        }
        if booking_details:
            payload["booking_details"] = booking_details
        if error:
            payload["error"] = error
            payload["status"] = "error"
        else:
            payload["status"] = "verified" if verified else "not_found"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.callback_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)):
                    pass
        except Exception as e:
            print(f"[verify-bot] Callback failed: {e}")

    async def run(self):
        result = {"success": False, "verified": False, "booking_details": None, "error": None}
        try:
            await self._launch_browser()
            await self._navigate_and_fill()
            booking_details = await self._check_result()
            if booking_details:
                result["success"] = True
                result["verified"] = True
                result["booking_details"] = booking_details
                await self.send_callback(True, booking_details)
            else:
                result["success"] = True
                result["verified"] = False
                result["error"] = "Booking not found or invalid credentials"
                await self.send_callback(False, error="Booking not found or invalid credentials")
        except Exception as e:
            error_msg = str(e)
            print(f"[verify-bot] Error: {error_msg}")
            traceback.print_exc()
            result["error"] = error_msg
            await self.send_callback(False, error=error_msg)
        finally:
            await self._cleanup()
        return result

    async def _launch_browser(self):
        print(f"[verify-bot] Launching browser (job: {self.job_id})...")
        self.stealth = Stealth()
        self.pw_cm = self.stealth.use_async(async_playwright())
        self.playwright = await self.pw_cm.__aenter__()
        launch_kwargs = dict(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        chromium_path = shutil.which("chromium") or shutil.which("chromium-browser")
        if chromium_path:
            launch_kwargs["executable_path"] = chromium_path
        self.browser = await self.playwright.chromium.launch(**launch_kwargs)
        context = await self.browser.new_context(
            user_agent=config.USER_AGENT,
            viewport={"width": 1366, "height": 900},
        )
        self.page = await context.new_page()

    async def _navigate_and_fill(self):
        print(f"[verify-bot] Navigating to booking page...")
        await self.page.goto(VERIFY_URL, wait_until="domcontentloaded", timeout=config.PAGE_LOAD_TIMEOUT)
        await asyncio.sleep(2)

        cookie_selectors = [
            "button#onetrust-accept-btn-handler",
            "button[id*='accept']",
            "button:has-text('Accept')",
        ]
        for sel in cookie_selectors:
            try:
                btn = self.page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    await asyncio.sleep(1)
                    break
            except Exception:
                continue

        print(f"[verify-bot] Filling booking code: {self.booking_code}")
        code_input = self.page.locator("input[id*='CONFIRMATIONNUMBER'], input[id*='InputCode'], input[name*='CONFIRMATIONNUMBER']").first
        await code_input.wait_for(state="visible", timeout=15000)
        await code_input.clear()
        await code_input.fill(self.booking_code)

        print(f"[verify-bot] Filling email: {self.email}")
        email_input = self.page.locator("input[id*='CONTACTEMAIL'], input[id*='InputEmail'], input[name*='CONTACTEMAIL']").first
        await email_input.wait_for(state="visible", timeout=10000)
        await email_input.clear()
        await email_input.fill(self.email)

        print(f"[verify-bot] Clicking GO...")
        go_button = self.page.locator("a[id*='LinkButtonRetrieve'], a.btn--primary:has-text('Go')").first
        await go_button.wait_for(state="visible", timeout=10000)
        await go_button.click()

        await self.page.wait_for_load_state("domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

    async def _check_result(self):
        print(f"[verify-bot] Checking booking result...")
        page = self.page

        booking_found = False
        try:
            flight_box = page.locator(".flightDetailsBox, .flightDetailsBox__date, [class*='flightDetailsBox']").first
            if await flight_box.is_visible(timeout=5000):
                booking_found = True
        except Exception:
            pass

        if not booking_found:
            body_text = await page.locator("body").text_content()
            if self.booking_code.upper() in body_text.upper() and "Flight" in body_text:
                booking_found = True

        if not booking_found:
            print(f"[verify-bot] Booking not found on page")
            return None

        print(f"[verify-bot] Booking found! Extracting details...")
        import re

        details = {"booking_code": self.booking_code, "exists": True, "flights": []}

        flight_boxes = await page.locator(".sectionBorderTab.flightDetailsBox").all()
        if not flight_boxes:
            flight_boxes = await page.locator("[class*='flightDetailsBox'][class*='sectionBorderTab']").all()
        if not flight_boxes:
            flight_boxes = [page.locator(".flightDetailsBox").first]

        for box in flight_boxes:
            flight = {}
            try:
                date_text = await box.locator(".flightDetailsBox__date").first.text_content(timeout=3000)
                date_match = re.search(r"(\d{1,2}[./]\d{1,2}[./]\d{2,4})", date_text)
                if date_match:
                    flight["flight_date"] = date_match.group(1)
                if "outbound" in date_text.lower():
                    flight["direction"] = "outbound"
                elif "inbound" in date_text.lower() or "return" in date_text.lower():
                    flight["direction"] = "return"
            except Exception:
                pass

            try:
                places = await box.locator(".flightDetailsBox__infoFLight__place").all()
                if len(places) >= 2:
                    flight["origin_city"] = (await places[0].text_content()).strip()
                    flight["destination_city"] = (await places[1].text_content()).strip()
            except Exception:
                pass

            try:
                terminals = await box.locator(".flightDetailsBox__infoFLight__terminal").all()
                if len(terminals) >= 2:
                    origin_term = (await terminals[0].text_content()).strip()
                    dest_term = (await terminals[1].text_content()).strip()
                    origin_code = re.search(r"([A-Z]{3})", origin_term)
                    dest_code = re.search(r"([A-Z]{3})", dest_term)
                    if origin_code:
                        flight["origin"] = origin_code.group(1)
                    if dest_code:
                        flight["destination"] = dest_code.group(1)
                    flight["origin_terminal"] = origin_term
                    flight["destination_terminal"] = dest_term
            except Exception:
                pass

            try:
                times = await box.locator(".flightDetailsBox__infoFLight__time").all()
                if len(times) >= 2:
                    flight["departure_time"] = (await times[0].text_content()).strip()
                    flight["arrival_time"] = (await times[1].text_content()).strip()
            except Exception:
                pass

            try:
                content_text = await box.locator(".flightDetailsBox__infoFLight__sectionContent").first.text_content(timeout=3000)
                flight_match = re.search(r"(?:Flight\s*N[°ºo]?\s*:?\s*)(VY\d+)", content_text, re.IGNORECASE)
                if flight_match:
                    flight["flight_number"] = flight_match.group(1)
            except Exception:
                pass

            if flight:
                details["flights"].append(flight)

        if details["flights"]:
            first = details["flights"][0]
            for key in ["flight_date", "direction", "origin_city", "destination_city",
                        "origin", "destination", "origin_terminal", "destination_terminal",
                        "departure_time", "arrival_time", "flight_number"]:
                if key in first:
                    details[key] = first[key]

        try:
            body_text = await page.locator("body").text_content()
            adults = re.search(r"(\d+)\s*Adult", body_text, re.IGNORECASE)
            if adults:
                details["passengers"] = int(adults.group(1))
        except Exception:
            pass

        print(f"[verify-bot] Details: {details}")
        return details

    async def _cleanup(self):
        try:
            if self.browser:
                await self.browser.close()
            if self.pw_cm:
                await self.pw_cm.__aexit__(None, None, None)
        except Exception:
            pass
