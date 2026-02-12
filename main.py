import asyncio
import os
import random
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright, Page, Frame, TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth

import config


class VuelingRefundBot:
    def __init__(
        self,
        booking_code: str = None,
        email: str = None,
        reason: str = None,
        document_path: str = None,
        headless: bool = None,
    ):
        self.booking_code = booking_code or config.BOOKING_CODE
        self.email = email or config.EMAIL
        self.reason = reason or config.REASON
        self.document_path = document_path or config.DOCUMENT_PATH
        self.headless = headless if headless is not None else config.HEADLESS
        self.browser = None
        self.page = None
        self.step_count = 0

        os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)

    async def _random_delay(self, min_s=None, max_s=None):
        lo = min_s or config.MIN_DELAY
        hi = max_s or config.MAX_DELAY
        delay = random.uniform(lo, hi)
        await asyncio.sleep(delay)

    async def _screenshot(self, label: str):
        self.step_count += 1
        name = f"{self.step_count:02d}_{label}.png"
        path = os.path.join(config.SCREENSHOTS_DIR, name)
        await self.page.screenshot(path=path, full_page=True)
        print(f"  [screenshot] {path}")

    async def _find_chatbot_frame(self) -> Frame | Page:
        for frame in self.page.frames:
            try:
                el = await frame.query_selector("[data-testid], .chat-container, .webchat, #webchat")
                if el:
                    print("  [info] Chatbot found inside iframe")
                    return frame
            except Exception:
                continue
        return self.page

    async def _click_text(self, ctx, text: str, timeout=None):
        timeout = timeout or config.STEP_TIMEOUT
        selectors = [
            f'button:has-text("{text}")',
            f'div[role="button"]:has-text("{text}")',
            f'span:has-text("{text}")',
            f'a:has-text("{text}")',
            f'text="{text}"',
        ]
        for sel in selectors:
            try:
                el = ctx.locator(sel).first
                await el.wait_for(state="visible", timeout=5000)
                await el.click()
                print(f"  [click] '{text}' via {sel}")
                return True
            except Exception:
                continue

        try:
            el = ctx.get_by_text(text, exact=False).first
            await el.wait_for(state="visible", timeout=5000)
            await el.click()
            print(f"  [click] '{text}' via get_by_text")
            return True
        except Exception:
            pass

        raise Exception(f"Could not find clickable element with text: '{text}'")

    async def _fill_input(self, ctx, placeholder_or_label: str, value: str, timeout=None):
        timeout = timeout or config.STEP_TIMEOUT
        selectors = [
            f'input[placeholder*="{placeholder_or_label}" i]',
            f'input[aria-label*="{placeholder_or_label}" i]',
            f'textarea[placeholder*="{placeholder_or_label}" i]',
        ]
        for sel in selectors:
            try:
                el = ctx.locator(sel).first
                await el.wait_for(state="visible", timeout=5000)
                await el.fill(value)
                print(f"  [fill] '{placeholder_or_label}' = '{value}'")
                return True
            except Exception:
                continue

        try:
            el = ctx.get_by_label(placeholder_or_label, exact=False).first
            await el.wait_for(state="visible", timeout=5000)
            await el.fill(value)
            print(f"  [fill] '{placeholder_or_label}' via label = '{value}'")
            return True
        except Exception:
            pass

        try:
            inputs = ctx.locator("input:visible, textarea:visible")
            count = await inputs.count()
            for i in range(count):
                inp = inputs.nth(i)
                ph = await inp.get_attribute("placeholder") or ""
                lbl = await inp.get_attribute("aria-label") or ""
                if placeholder_or_label.lower() in ph.lower() or placeholder_or_label.lower() in lbl.lower():
                    await inp.fill(value)
                    print(f"  [fill] input #{i} = '{value}'")
                    return True
        except Exception:
            pass

        raise Exception(f"Could not find input for: '{placeholder_or_label}'")

    async def _wait_for_new_content(self, ctx, timeout=None):
        timeout = timeout or config.STEP_TIMEOUT
        try:
            await ctx.locator(".message, .chat-message, [class*='message'], [class*='bubble']").last.wait_for(
                state="visible", timeout=timeout
            )
        except Exception:
            await asyncio.sleep(3)

    async def launch_browser(self):
        print("[1/8] Launching browser...")
        self.stealth = Stealth()
        self.pw_cm = self.stealth.use_async(async_playwright())
        self.playwright = await self.pw_cm.__aenter__()
        import shutil
        chromium_path = shutil.which("chromium") or shutil.which("chromium-browser")
        launch_kwargs = dict(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        if chromium_path:
            launch_kwargs["executable_path"] = chromium_path
        self.browser = await self.playwright.chromium.launch(**launch_kwargs)
        context = await self.browser.new_context(
            user_agent=config.USER_AGENT,
            viewport={"width": 1366, "height": 900},
            locale="en-US",
        )
        self.page = await context.new_page()
        print("  Browser launched successfully")

    async def navigate_to_refund_page(self):
        print("[2/8] Navigating to Vueling refund page...")
        await self.page.goto(config.VUELING_REFUND_URL, wait_until="domcontentloaded", timeout=config.PAGE_LOAD_TIMEOUT)
        await self._random_delay(2, 4)

        try:
            cookie_selectors = [
                'button:has-text("Accept")',
                'button:has-text("Aceptar")',
                'button[id*="cookie"]',
                '#onetrust-accept-btn-handler',
                'button:has-text("I agree")',
                'button:has-text("OK")',
            ]
            for sel in cookie_selectors:
                try:
                    btn = self.page.locator(sel).first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        print("  [info] Cookie banner dismissed")
                        break
                except Exception:
                    continue
        except Exception:
            print("  [info] No cookie banner found")

        await self._screenshot("page_loaded")
        await self._random_delay()

    async def wait_for_chatbot(self):
        print("[3/8] Waiting for chatbot to load...")
        chatbot_selectors = [
            "iframe[src*='chat']",
            "iframe[src*='bot']",
            "[class*='chat']",
            "[class*='webchat']",
            "[id*='webchat']",
            "[data-testid*='chat']",
        ]
        found = False
        for sel in chatbot_selectors:
            try:
                await self.page.wait_for_selector(sel, timeout=10000)
                print(f"  [info] Chatbot element found: {sel}")
                found = True
                break
            except Exception:
                continue

        if not found:
            print("  [warn] No chatbot selector matched, waiting extra time...")
            await asyncio.sleep(5)

        await self._screenshot("chatbot_loaded")
        await self._random_delay()

    async def select_code_and_email(self):
        print("[4/8] Selecting 'CODE AND EMAIL' option...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay()

        try:
            await self._click_text(ctx, "CODE AND EMAIL")
        except Exception:
            try:
                await self._click_text(ctx, "Code and email")
            except Exception:
                await self._click_text(ctx, "code")

        await self._screenshot("code_email_selected")
        await self._random_delay()

    async def fill_booking_details(self):
        print("[5/8] Filling booking details...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay()

        try:
            await self._fill_input(ctx, "code", self.booking_code)
        except Exception:
            try:
                await self._fill_input(ctx, "booking", self.booking_code)
            except Exception:
                inputs = ctx.locator("input:visible")
                first_input = inputs.first
                await first_input.fill(self.booking_code)
                print(f"  [fill] first visible input = '{self.booking_code}'")

        await self._random_delay(0.5, 1.5)

        try:
            await self._fill_input(ctx, "email", self.email)
        except Exception:
            inputs = ctx.locator("input:visible")
            count = await inputs.count()
            if count >= 2:
                await inputs.nth(1).fill(self.email)
                print(f"  [fill] second visible input = '{self.email}'")

        await self._screenshot("booking_details_filled")
        await self._random_delay()

    async def click_send(self):
        print("[6/8] Clicking SEND...")
        ctx = await self._find_chatbot_frame()

        try:
            await self._click_text(ctx, "SEND")
        except Exception:
            try:
                await self._click_text(ctx, "Send")
            except Exception:
                try:
                    submit = ctx.locator('button[type="submit"], input[type="submit"]').first
                    await submit.click()
                    print("  [click] submit button")
                except Exception:
                    await self._click_text(ctx, "Enviar")

        await self._screenshot("send_clicked")
        print("  Waiting for booking verification...")
        await self._wait_for_new_content(ctx)
        await self._random_delay(2, 4)
        await self._screenshot("verification_response")

    async def select_cancellation_reason(self):
        print("[7/8] Selecting cancellation reason...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay()

        try:
            await self._click_text(ctx, self.reason)
        except Exception:
            try:
                await self._click_text(ctx, "ILL")
            except Exception:
                await self._click_text(ctx, "ill")

        await self._screenshot("reason_selected")
        await self._wait_for_new_content(ctx)
        await self._random_delay()

    async def handle_documents(self):
        print("[8/8] Handling document upload...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay()

        try:
            await self._click_text(ctx, "YES")
        except Exception:
            try:
                await self._click_text(ctx, "Yes")
            except Exception:
                await self._click_text(ctx, "yes")

        await self._random_delay()
        await self._screenshot("yes_clicked")

        if self.document_path and os.path.exists(self.document_path):
            print(f"  Uploading document: {self.document_path}")
            try:
                file_input = ctx.locator('input[type="file"]').first
                await file_input.set_input_files(self.document_path)
                print("  [upload] Document uploaded successfully")
                await self._random_delay()
            except Exception as e:
                print(f"  [warn] File upload failed: {e}")
                try:
                    async with self.page.expect_file_chooser() as fc_info:
                        upload_btn_selectors = [
                            'button:has-text("Upload")',
                            'button:has-text("Attach")',
                            'button:has-text("Browse")',
                            '[class*="upload"]',
                            '[class*="attach"]',
                        ]
                        for sel in upload_btn_selectors:
                            try:
                                btn = ctx.locator(sel).first
                                if await btn.is_visible(timeout=2000):
                                    await btn.click()
                                    break
                            except Exception:
                                continue
                    file_chooser = await fc_info.value
                    await file_chooser.set_files(self.document_path)
                    print("  [upload] Document uploaded via file chooser")
                except Exception as e2:
                    print(f"  [error] File upload also failed with file chooser: {e2}")
        else:
            print(f"  [warn] Document not found at: {self.document_path}")

        await self._screenshot("document_uploaded")
        await self._random_delay()

        try:
            submit_selectors = ["Submit", "SUBMIT", "Send", "SEND", "Confirm", "CONFIRM"]
            for text in submit_selectors:
                try:
                    await self._click_text(ctx, text)
                    print(f"  [click] Final submit: '{text}'")
                    break
                except Exception:
                    continue
        except Exception:
            print("  [info] No additional submit button found")

        await self._random_delay(2, 4)
        await self._screenshot("final_confirmation")

    async def run(self):
        print("=" * 60)
        print("Vueling Refund Bot")
        print("=" * 60)
        print(f"  Booking Code : {self.booking_code}")
        print(f"  Email        : {self.email}")
        print(f"  Reason       : {self.reason}")
        print(f"  Document     : {self.document_path}")
        print(f"  Headless     : {self.headless}")
        print("=" * 60)

        try:
            await self.launch_browser()
            await self.navigate_to_refund_page()
            await self.wait_for_chatbot()
            await self.select_code_and_email()
            await self.fill_booking_details()
            await self.click_send()
            await self.select_cancellation_reason()
            await self.handle_documents()

            print("\n" + "=" * 60)
            print("Bot completed all steps successfully!")
            print(f"Screenshots saved to: {config.SCREENSHOTS_DIR}/")
            print("=" * 60)

        except Exception as e:
            print(f"\n[ERROR] Bot failed: {e}")
            try:
                await self._screenshot("error_state")
            except Exception:
                pass
            raise

        finally:
            if self.browser:
                await self.browser.close()
            if hasattr(self, "pw_cm"):
                await self.pw_cm.__aexit__(None, None, None)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Vueling Refund Chatbot Automation Bot")
    parser.add_argument("--booking-code", type=str, help="Booking confirmation code")
    parser.add_argument("--email", type=str, help="Email used for the booking")
    parser.add_argument("--reason", type=str, help="Cancellation reason")
    parser.add_argument("--document", type=str, help="Path to medical certificate file")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument("--no-headless", action="store_true", help="Run with visible browser")

    args = parser.parse_args()

    headless = None
    if args.headless:
        headless = True
    elif args.no_headless:
        headless = False

    bot = VuelingRefundBot(
        booking_code=args.booking_code,
        email=args.email,
        reason=args.reason,
        document_path=args.document,
        headless=headless,
    )

    asyncio.run(bot.run())


if __name__ == "__main__":
    main()
