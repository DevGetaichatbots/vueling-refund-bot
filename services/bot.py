import asyncio
import os
import random
import re
import shutil
import traceback
from pathlib import Path

import aiohttp
from playwright.async_api import async_playwright, Page, Frame
from playwright_stealth import Stealth

import config

STEP_CALLBACK_MAP = {
    "Launch Browser": ("navigating_to_portal", "Opening airline refund portal", 5),
    "Navigate": ("navigating_to_portal", "Opening airline refund portal", 10),
    "Wait for Chatbot": ("navigating_to_portal", "Connecting to refund system", 15),
    "Select CODE AND EMAIL": ("entering_booking", "Preparing booking lookup", 20),
    "Fill Booking Details": ("entering_booking", "Entering booking reference", 25),
    "Select Reason": ("selecting_refund_type", "Selecting refund type", 30),
    "Confirm Documents": ("filling_passenger", "Confirming document readiness", 35),
    "Fill Name": ("filling_passenger", "Filling passenger details", 40),
    "Contact Email": ("filling_passenger", "Submitting contact information", 45),
    "Fill Phone": ("filling_passenger", "Entering phone number", 50),
    "Submit Comment": ("submitting_claim", "Submitting additional details", 60),
    "Upload Documents": ("uploading_documents", "Uploading supporting documents", 70),
    "Get Confirmation": ("submitting_claim", "Submitting refund request", 85),
    "Decline Another": ("completed", "Refund claim submitted successfully", 100),
}


class BotStepError(Exception):
    def __init__(self, step_name, message, screenshot_path=None):
        self.step_name = step_name
        self.screenshot_path = screenshot_path
        super().__init__(f"[{step_name}] {message}")


class VuelingRefundBot:
    def __init__(
        self,
        booking_code=None,
        email=None,
        reason=None,
        first_name=None,
        surname=None,
        contact_email=None,
        phone_prefix=None,
        phone_number=None,
        comment=None,
        document_paths=None,
        headless=None,
        job_id=None,
        on_progress=None,
        callback_url=None,
        claim_id=None,
    ):
        self.booking_code = booking_code or config.BOOKING_CODE
        self.email = email or config.EMAIL
        self.reason = reason or config.REASON
        self.first_name = first_name or ""
        self.surname = surname or ""
        self.contact_email = contact_email or ""
        self.phone_prefix = phone_prefix or "+92"
        self.phone_number = phone_number or ""
        self.comment = comment if comment else ""
        self.document_paths = document_paths or []
        self.headless = headless if headless is not None else config.HEADLESS
        self.job_id = job_id or "manual"
        self.on_progress = on_progress
        self.callback_url = callback_url
        self.claim_id = claim_id
        self.browser = None
        self.page = None
        self.step_count = 0
        self.completed_steps = []
        self.errors = []
        self.case_number = None

        self.screenshots_dir = os.path.join(config.SCREENSHOTS_DIR, self.job_id)
        os.makedirs(self.screenshots_dir, exist_ok=True)

    async def _send_status_callback(self, step_name, status="in_progress", error_message=None):
        if not self.callback_url:
            return

        mapping = STEP_CALLBACK_MAP.get(step_name)
        if not mapping:
            return

        step_key, default_message, progress = mapping
        payload = {
            "claimId": self.claim_id or self.job_id,
            "step": "error" if status == "error" else step_key,
            "message": error_message if error_message else default_message,
            "progress": progress,
            "status": status,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.callback_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    print(f"  [callback] Sent {step_key} ({progress}%) -> {resp.status}")
        except Exception as e:
            print(f"  [callback] Failed to send status update: {e}")

    async def _notify_progress(self):
        if self.on_progress:
            screenshots_dir = Path(self.screenshots_dir)
            screenshots = sorted([str(p) for p in screenshots_dir.glob("*.png")]) if screenshots_dir.exists() else []
            result = self.on_progress(
                completed_steps=list(self.completed_steps),
                errors=list(self.errors),
                screenshots=screenshots,
                case_number=self.case_number,
            )
            if asyncio.iscoroutine(result):
                await result

    async def _random_delay(self, min_s=None, max_s=None):
        lo = min_s or config.MIN_DELAY
        hi = max_s or config.MAX_DELAY
        await asyncio.sleep(random.uniform(lo, hi))

    async def _screenshot(self, label):
        self.step_count += 1
        name = f"{self.step_count:02d}_{label}.png"
        path = os.path.join(self.screenshots_dir, name)
        try:
            await self.page.screenshot(path=path, full_page=True)
            print(f"  [screenshot] {path}")
            return path
        except Exception as e:
            print(f"  [warn] Screenshot failed: {e}")
            return None

    async def _find_chatbot_frame(self):
        for frame in self.page.frames:
            try:
                el = await frame.query_selector("[data-testid], .chat-container, .webchat, #webchat")
                if el:
                    return frame
            except Exception:
                continue
        return self.page

    async def _click_text(self, ctx, text, timeout=None):
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

    async def _fill_input(self, ctx, placeholder_or_label, value, timeout=None):
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

    async def _type_in_chat(self, ctx, message):
        try:
            chat_input = ctx.locator('input[placeholder*="reply" i], input[placeholder*="write" i], textarea[placeholder*="reply" i], textarea[placeholder*="write" i]').first
            await chat_input.wait_for(state="visible", timeout=10000)
            await chat_input.fill(message)
            await self._random_delay(0.3, 0.8)
            await chat_input.press("Enter")
            print(f"  [chat] Typed: '{message}'")
            return True
        except Exception:
            pass

        try:
            chat_input = ctx.locator("input:visible, textarea:visible").last
            await chat_input.fill(message)
            await self._random_delay(0.3, 0.8)
            await chat_input.press("Enter")
            print(f"  [chat] Typed via last input: '{message}'")
            return True
        except Exception:
            raise Exception(f"Could not type in chat: '{message}'")

    async def _get_message_count(self, ctx):
        selectors = [
            ".message", ".chat-message", "[class*='message']",
            "[class*='bubble']", "[class*='response']", "[class*='answer']",
        ]
        max_count = 0
        for sel in selectors:
            try:
                count = await ctx.locator(sel).count()
                if count > max_count:
                    max_count = count
            except Exception:
                continue
        return max_count

    async def _wait_for_new_content(self, ctx, timeout=None, min_wait=2, max_wait=8, expect_selector=None):
        timeout = timeout or config.STEP_TIMEOUT
        before_count = await self._get_message_count(ctx)
        print(f"  [wait] Waiting for chatbot response (current messages: {before_count})...")

        deadline = asyncio.get_event_loop().time() + (timeout / 1000)
        poll_interval = 0.5
        new_content_found = False

        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(poll_interval)
            current_count = await self._get_message_count(ctx)
            if current_count > before_count:
                print(f"  [wait] New content detected (messages: {before_count} -> {current_count})")
                new_content_found = True
                break

        if new_content_found:
            await asyncio.sleep(min_wait)
            stable_count = await self._get_message_count(ctx)
            retries = 0
            while retries < 3:
                await asyncio.sleep(1)
                new_stable = await self._get_message_count(ctx)
                if new_stable == stable_count:
                    break
                stable_count = new_stable
                retries += 1
            print(f"  [wait] Chatbot response stabilized (messages: {stable_count})")
        else:
            print(f"  [wait] No new messages detected, waiting {max_wait}s as fallback...")
            await asyncio.sleep(max_wait)

        if expect_selector:
            try:
                el = ctx.locator(expect_selector).first
                await el.wait_for(state="visible", timeout=15000)
                print(f"  [wait] Expected element found: {expect_selector}")
            except Exception:
                print(f"  [wait] Expected element not found yet: {expect_selector}, waiting extra...")
                await asyncio.sleep(5)

    async def _run_step(self, step_name, step_func, *args, retries=2, **kwargs):
        for attempt in range(1, retries + 1):
            try:
                result = await step_func(*args, **kwargs)
                self.completed_steps.append(step_name)
                await self._notify_progress()
                final_status = "completed" if step_name == "Decline Another" else "in_progress"
                await self._send_status_callback(step_name, status=final_status)
                return result
            except Exception as e:
                error_msg = f"Step '{step_name}' attempt {attempt}/{retries} failed: {e}"
                print(f"  [error] {error_msg}")
                if attempt < retries:
                    print(f"  [retry] Retrying in 3 seconds...")
                    await asyncio.sleep(3)
                else:
                    screenshot_path = await self._screenshot(f"error_{step_name.replace(' ', '_').lower()}")
                    self.errors.append({"step": step_name, "error": str(e), "screenshot": screenshot_path})
                    await self._notify_progress()
                    await self._send_status_callback(step_name, status="error", error_message=str(e))
                    raise BotStepError(step_name, str(e), screenshot_path)

    # ── Step 1: Launch browser ──
    async def step_launch_browser(self):
        print(f"[Step 1] Launching browser (job: {self.job_id})...")
        self.stealth = Stealth()
        self.pw_cm = self.stealth.use_async(async_playwright())
        self.playwright = await self.pw_cm.__aenter__()
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

    # ── Step 2: Navigate to refund page ──
    async def step_navigate(self):
        print("[Step 2] Navigating to Vueling refund page...")
        await self.page.goto(config.VUELING_REFUND_URL, wait_until="domcontentloaded", timeout=config.PAGE_LOAD_TIMEOUT)
        await self._random_delay(2, 4)

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
                    await self._random_delay(0.5, 1)
                    break
            except Exception:
                continue

        await self._screenshot("page_loaded")
        await self._random_delay()

    # ── Step 3: Wait for chatbot ──
    async def step_wait_chatbot(self):
        print("[Step 3] Waiting for chatbot to load...")
        chatbot_selectors = [
            "iframe[src*='chat']", "iframe[src*='bot']",
            "[class*='chat']", "[class*='webchat']",
            "[id*='webchat']", "[data-testid*='chat']",
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

    # ── Step 4: Select CODE AND EMAIL ──
    async def step_select_code_email(self):
        print("[Step 4] Selecting 'CODE AND EMAIL'...")
        ctx = await self._find_chatbot_frame()

        clicked = False
        for text in ["CODE AND EMAIL", "Code and email", "code and email", "code"]:
            try:
                await self._click_text(ctx, text)
                await self._screenshot("code_email_selected")
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            raise Exception("Could not find 'CODE AND EMAIL' option")

        await self._wait_for_new_content(ctx, min_wait=2, max_wait=10, expect_selector="input:visible")
        await self._random_delay()

    # ── Step 5: Fill booking code + email → SEND ──
    async def step_fill_booking(self):
        print("[Step 5] Filling booking details...")
        ctx = await self._find_chatbot_frame()

        filled = False
        for label in ["code", "booking"]:
            try:
                await self._fill_input(ctx, label, self.booking_code)
                filled = True
                break
            except Exception:
                continue
        if not filled:
            inputs = ctx.locator("input:visible")
            await inputs.first.fill(self.booking_code)
            print(f"  [fill] first input = '{self.booking_code}'")

        await self._random_delay(0.2, 0.4)

        try:
            await self._fill_input(ctx, "email", self.email)
        except Exception:
            inputs = ctx.locator("input:visible")
            count = await inputs.count()
            if count >= 2:
                await inputs.nth(1).fill(self.email)
                print(f"  [fill] second input = '{self.email}'")

        await self._screenshot("booking_filled")
        await self._random_delay(0.2, 0.4)

        send_clicked = False
        send_selectors = ['button:has-text("SEND")', 'button:has-text("Send")']
        for sel in send_selectors:
            try:
                btns = ctx.locator(sel)
                count = await btns.count()
                for i in range(count - 1, -1, -1):
                    btn = btns.nth(i)
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        print(f"  [click] SEND clicked via {sel} (index {i})")
                        send_clicked = True
                        break
                if send_clicked:
                    break
            except Exception:
                continue

        if not send_clicked:
            for text in ["SEND", "Send"]:
                try:
                    await self._click_text(ctx, text)
                    send_clicked = True
                    break
                except Exception:
                    continue

        if not send_clicked:
            raise Exception("Could not click SEND button for booking details")

        await self._screenshot("send_clicked")
        print("  Waiting for booking verification and reason options...")
        verified = False
        for attempt in range(45):
            await asyncio.sleep(1)
            try:
                page_text = await ctx.locator("body").text_content() or ""
                lower_text = page_text.lower()
                if "ill" in lower_text or "pregnant" in lower_text or "court" in lower_text or "death" in lower_text or "reason" in lower_text or "cancellation" in lower_text:
                    print("  [wait] Booking verified - reason options detected")
                    verified = True
                    break
            except Exception:
                pass
        if not verified:
            print("  [wait] Reason options not detected after 45s, proceeding anyway")
        await asyncio.sleep(1)
        await self._screenshot("verification_response")

    # ── Step 6: Select cancellation reason ──
    async def step_select_reason(self):
        print(f"[Step 6] Selecting reason: {self.reason}...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay()

        try:
            reason_btn = ctx.locator('button:visible').first
            await reason_btn.wait_for(state="visible", timeout=15000)
            print("  [wait] Reason buttons are ready")
        except Exception:
            print("  [wait] Reason buttons not found, waiting for chatbot...")
            await self._wait_for_new_content(ctx, min_wait=2, max_wait=8)

        normalized_reason = self.reason.strip().upper()
        reason_map = {
            "ILL OR HAVING SURGERY": ["ILL OR HAVING SURGERY", "Ill or having surgery", "ILL"],
            "PREGNANT": ["PREGNANT", "Pregnant", "pregnant"],
            "COURT SUMMONS OR SERVICE AT POLLING STATION": ["COURT SUMMONS OR SERVICE AT POLLING STATION", "Court summons or service at polling station", "COURT SUMMONS", "Court summons"],
            "SOMEONE'S DEATH": ["SOMEONE'S DEATH", "Someone's death", "SOMEONE'S DEATH", "Someone's Death"],
        }
        reason_variants = reason_map.get(normalized_reason, [])
        reason_variants = [self.reason] + [v for v in reason_variants if v != self.reason]

        for text in reason_variants:
            try:
                await self._click_text(ctx, text)
                await self._screenshot("reason_selected")
                await self._wait_for_new_content(ctx, min_wait=3, max_wait=15)

                print("  [wait] Waiting for chatbot to finish all messages after reason selection...")
                for extra_wait in range(20):
                    await asyncio.sleep(1)
                    try:
                        page_text = await ctx.locator("body").text_content() or ""
                        if "document" in page_text.lower() and ("yes" in page_text.lower() or "hand" in page_text.lower()):
                            print("  [wait] Document/YES prompt detected in chatbot")
                            await asyncio.sleep(2)
                            break
                    except Exception:
                        pass
                else:
                    print("  [wait] Document prompt not detected after extra wait, proceeding")

                await self._random_delay()
                return
            except Exception:
                continue
        raise Exception(f"Could not find reason: '{self.reason}'")

    # ── Step 7: "Got all your documents to hand?" → YES ──
    async def step_confirm_documents(self):
        print("[Step 7] Confirming documents ready (YES)...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay()

        try:
            await ctx.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass

        yes_selectors = [
            'button:has-text("YES")',
            'button:has-text("Yes")',
            'div[role="button"]:has-text("YES")',
            'div[role="button"]:has-text("Yes")',
            'span:has-text("YES")',
            '[class*="button"]:has-text("YES")',
            '[class*="button"]:has-text("Yes")',
        ]

        yes_btn = None
        for attempt in range(30):
            try:
                await ctx.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass

            for sel in yes_selectors:
                try:
                    el = ctx.locator(sel).first
                    if await el.is_visible(timeout=500):
                        yes_btn = el
                        print(f"  [wait] YES button found via {sel} (attempt {attempt+1})")
                        break
                except Exception:
                    continue
            if yes_btn:
                break

            try:
                el = ctx.get_by_text("YES", exact=True).first
                if await el.is_visible(timeout=500):
                    yes_btn = el
                    print(f"  [wait] YES button found via get_by_text (attempt {attempt+1})")
                    break
            except Exception:
                pass

            if attempt % 5 == 4:
                print(f"  [wait] Still looking for YES button... (attempt {attempt+1}/30)")
            await asyncio.sleep(1)

        if not yes_btn:
            print("  [warn] YES button not found after 30s polling, trying text-based fallback...")
            await self._screenshot("yes_button_not_found")
            for text in ["YES", "Yes"]:
                try:
                    await self._click_text(ctx, text, timeout=10000)
                    print(f"  [click] YES clicked via _click_text fallback")
                    await self._screenshot("documents_confirmed")
                    await self._wait_for_new_content(ctx, min_wait=2, max_wait=10, expect_selector="input:visible")
                    await self._random_delay()
                    return
                except Exception:
                    continue
            raise Exception("Could not find YES button after extensive search")

        try:
            await yes_btn.scroll_into_view_if_needed()
            await asyncio.sleep(0.5)
        except Exception:
            pass

        try:
            await yes_btn.click()
            print("  [click] YES clicked")
        except Exception:
            try:
                await yes_btn.click(force=True)
                print("  [click] YES force-clicked")
            except Exception:
                raise Exception("YES button found but could not click it")

        await self._screenshot("documents_confirmed")
        await self._wait_for_new_content(ctx, min_wait=2, max_wait=10, expect_selector="input:visible")
        await self._random_delay()

    # ── Step 8: Enter first name + surname → SEND ──
    async def step_fill_name(self):
        print(f"[Step 8] Filling name: {self.first_name} {self.surname}...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay()

        try:
            name_input = ctx.locator('input:visible').first
            await name_input.wait_for(state="visible", timeout=15000)
            print("  [wait] Name form is ready")
        except Exception:
            print("  [wait] Name form not found, waiting for chatbot...")
            await self._wait_for_new_content(ctx, min_wait=2, max_wait=8, expect_selector="input:visible")

        first_filled = False
        for label in ["First name", "first"]:
            try:
                inp = ctx.get_by_label(label, exact=False).first
                await inp.wait_for(state="visible", timeout=5000)
                await inp.click()
                await inp.fill("")
                await inp.type(self.first_name, delay=50)
                print(f"  [type] '{label}' = '{self.first_name}'")
                first_filled = True
                break
            except Exception:
                continue
        if not first_filled:
            try:
                inp = ctx.locator('input[placeholder*="first" i]:visible, input[placeholder*="name" i]:visible').first
                await inp.click()
                await inp.fill("")
                await inp.type(self.first_name, delay=50)
                print(f"  [type] first input = '{self.first_name}'")
                first_filled = True
            except Exception:
                inputs = ctx.locator("input:visible")
                inp = inputs.first
                await inp.click()
                await inp.fill("")
                await inp.type(self.first_name, delay=50)
                print(f"  [type] first visible input = '{self.first_name}'")

        await self._random_delay(0.3, 0.5)

        surname_filled = False
        for label in ["Surname", "surname", "last"]:
            try:
                inp = ctx.get_by_label(label, exact=False).first
                await inp.wait_for(state="visible", timeout=5000)
                await inp.click()
                await inp.fill("")
                await inp.type(self.surname, delay=50)
                print(f"  [type] '{label}' = '{self.surname}'")
                surname_filled = True
                break
            except Exception:
                continue
        if not surname_filled:
            try:
                inputs = ctx.locator("input:visible")
                count = await inputs.count()
                if count >= 2:
                    inp = inputs.nth(1)
                    await inp.click()
                    await inp.fill("")
                    await inp.type(self.surname, delay=50)
                    print(f"  [type] second input = '{self.surname}'")
            except Exception:
                pass

        await self._screenshot("name_filled")
        await self._random_delay(0.3, 0.5)

        before_text = ""
        try:
            before_text = await ctx.locator("body").text_content() or ""
        except Exception:
            pass

        send_clicked = False
        send_selectors = [
            'button:has-text("SEND")',
            'button:has-text("Send")',
            'button:has-text("send")',
            '[type="submit"]:visible',
            'div:has-text("SEND"):visible',
            'span:has-text("SEND"):visible',
        ]
        for sel in send_selectors:
            try:
                btns = ctx.locator(sel)
                count = await btns.count()
                for i in range(count - 1, -1, -1):
                    btn = btns.nth(i)
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        print(f"  [click] SEND clicked via {sel} (index {i})")
                        send_clicked = True
                        break
                if send_clicked:
                    break
            except Exception:
                continue

        if not send_clicked:
            for sel in send_selectors[:3]:
                try:
                    btn = ctx.locator(sel).last
                    await btn.click(force=True)
                    print(f"  [click] SEND force-clicked via {sel}")
                    send_clicked = True
                    break
                except Exception:
                    continue

        if not send_clicked:
            print("  [warn] SEND button not found, trying Enter key on surname input")
            try:
                surname_input = ctx.get_by_label("Surname", exact=False).first
                await surname_input.press("Enter")
                print("  [click] Pressed Enter on surname input")
                send_clicked = True
            except Exception:
                try:
                    last_input = ctx.locator("input:visible").last
                    await last_input.press("Enter")
                    print("  [click] Pressed Enter on last input")
                    send_clicked = True
                except Exception:
                    raise Exception("Could not submit name form - no SEND button or Enter key worked")

        await self._wait_for_new_content(ctx, min_wait=2, max_wait=20, expect_selector=None)

        print("  [wait] Waiting for chatbot to ask for email...")
        email_prompt_found = False
        for attempt in range(25):
            await asyncio.sleep(1)
            try:
                page_text = await ctx.locator("body").text_content() or ""
                if "email" in page_text.lower() and "contact" in page_text.lower():
                    if page_text != before_text:
                        print("  [wait] Email prompt detected in chatbot response")
                        email_prompt_found = True
                        break
            except Exception:
                pass
        if not email_prompt_found:
            print("  [wait] Email prompt not detected after 25s, proceeding anyway")
        await asyncio.sleep(1)

        await self._screenshot("name_sent")

    # ── Step 9: Enter contact email (type in chat) ──
    async def step_contact_email(self):
        print(f"[Step 9] Entering contact email: {self.contact_email}...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay(0.5, 1)

        email_prompt_visible = False
        try:
            page_text = await ctx.locator("body").text_content() or ""
            if "email" in page_text.lower() and "contact" in page_text.lower():
                email_prompt_visible = True
                print("  [wait] Email prompt is visible, proceeding to type email")
        except Exception:
            pass

        if not email_prompt_visible:
            print("  [wait] Waiting for email prompt from chatbot...")
            for attempt in range(20):
                await asyncio.sleep(1)
                try:
                    page_text = await ctx.locator("body").text_content() or ""
                    if "email" in page_text.lower():
                        print("  [wait] Email prompt appeared")
                        email_prompt_visible = True
                        break
                except Exception:
                    pass
            if not email_prompt_visible:
                print("  [warn] Email prompt never appeared, trying anyway")
            await asyncio.sleep(1)

        await self._type_in_chat(ctx, self.contact_email)
        await self._screenshot("contact_email_sent")

        await self._wait_for_new_content(ctx, min_wait=2, max_wait=15, expect_selector="select:visible, input[type='tel']:visible")

        print("  [wait] Waiting for phone form to appear...")
        phone_form_found = False
        for attempt in range(20):
            await asyncio.sleep(1)
            try:
                page_text = await ctx.locator("body").text_content() or ""
                if "phone" in page_text.lower() or "prefix" in page_text.lower():
                    print("  [wait] Phone form prompt detected")
                    phone_form_found = True
                    break
            except Exception:
                pass
        if not phone_form_found:
            print("  [wait] Phone prompt not detected after 30s, proceeding anyway")
        await asyncio.sleep(1)

    # ── Step 10: Enter phone country + number → SEND ──
    async def step_fill_phone(self):
        print(f"[Step 10] Filling phone: {self.phone_prefix} {self.phone_number}...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay()

        phone_ready = False
        for sel in ['select:visible', 'input[type="tel"]:visible', 'input[placeholder*="phone" i]:visible']:
            try:
                el = ctx.locator(sel).first
                await el.wait_for(state="visible", timeout=15000)
                print(f"  [wait] Phone form ready (found: {sel})")
                phone_ready = True
                break
            except Exception:
                continue
        if not phone_ready:
            print("  [wait] Phone form not detected, waiting for chatbot...")
            await self._wait_for_new_content(ctx, min_wait=3, max_wait=12)
        await self._screenshot("phone_step_ready")

        raw_prefix = self.phone_prefix.lstrip("+")
        country_selected = False
        print(f"  [info] Using exact prefix: +{raw_prefix}")

        try:
            native_select = ctx.locator("select:visible:not([disabled])").first
            await native_select.wait_for(state="visible", timeout=5000)
            options = await native_select.locator("option").all()

            option_data = []
            for option in options:
                opt_text = await option.text_content() or ""
                opt_val = await option.get_attribute("value") or ""
                if opt_val and not await option.get_attribute("disabled"):
                    option_data.append((opt_text, opt_val))

            for opt_text, opt_val in option_data:
                if f"(+{raw_prefix})" in opt_text or opt_val == f"+{raw_prefix}" or opt_val == raw_prefix:
                    await native_select.select_option(value=opt_val)
                    print(f"  [select] Country prefix matched: {opt_text.strip()} (value={opt_val})")
                    country_selected = True
                    break
        except Exception as e:
            print(f"  [info] Native select not found: {e}")

        if not country_selected:
            print(f"  [warn] Could not select country prefix +{raw_prefix}, proceeding with default")

        await self._random_delay(0.5, 1)
        await self._screenshot("prefix_selected")

        full_phone = self.phone_number
        print(f"  [info] Phone number (digits only): '{full_phone}'")

        phone_filled = False
        phone_selectors = [
            'input[placeholder*="phone" i]:visible',
            'input[placeholder*="Mobile" i]:visible',
            'input[type="tel"]:visible:not([disabled])',
            'input[type="number"]:visible:not([disabled])',
        ]
        for sel in phone_selectors:
            try:
                phone_input = ctx.locator(sel).first
                await phone_input.wait_for(state="visible", timeout=5000)
                await phone_input.fill(full_phone)
                print(f"  [fill] phone input via '{sel}' = '{full_phone}'")
                phone_filled = True
                break
            except Exception:
                continue

        if not phone_filled:
            try:
                enabled_inputs = ctx.locator('input:visible:not([disabled]):not([type="email"])')
                count = await enabled_inputs.count()
                for i in range(count):
                    inp = enabled_inputs.nth(i)
                    inp_type = await inp.get_attribute("type") or "text"
                    inp_val = await inp.get_attribute("value") or ""
                    placeholder = await inp.get_attribute("placeholder") or ""
                    if inp_type in ("text", "tel", "number") and not inp_val and "prefix" not in placeholder.lower():
                        await inp.fill(self.phone_number)
                        print(f"  [fill] phone input #{i} = '{self.phone_number}'")
                        phone_filled = True
                        break
            except Exception:
                pass

        if not phone_filled:
            raise Exception("Could not find phone number input field")

        await self._screenshot("phone_filled")
        await self._random_delay(0.3, 0.5)

        send_clicked = False
        send_selectors = ['button:has-text("SEND")', 'button:has-text("Send")']
        for sel in send_selectors:
            try:
                btns = ctx.locator(sel)
                count = await btns.count()
                for i in range(count - 1, -1, -1):
                    btn = btns.nth(i)
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        print(f"  [click] Phone SEND clicked via {sel} (index {i})")
                        send_clicked = True
                        break
                if send_clicked:
                    break
            except Exception:
                continue

        if not send_clicked:
            for sel in send_selectors:
                try:
                    await ctx.locator(sel).last.click(force=True)
                    print(f"  [click] Phone SEND force-clicked via {sel}")
                    send_clicked = True
                    break
                except Exception:
                    continue

        if not send_clicked:
            raise Exception("Could not click SEND button for phone number")

        await self._wait_for_new_content(ctx, min_wait=2, max_wait=15, expect_selector='button:has-text("SUBMIT"), textarea:visible')

        print("  [wait] Waiting for comment/submit prompt...")
        comment_prompt_found = False
        for attempt in range(15):
            await asyncio.sleep(1)
            try:
                page_text = await ctx.locator("body").text_content() or ""
                if "comment" in page_text.lower() or "submit query" in page_text.lower() or "more information" in page_text.lower():
                    print("  [wait] Comment/submit prompt detected")
                    comment_prompt_found = True
                    break
            except Exception:
                pass
        if not comment_prompt_found:
            print("  [wait] Comment prompt not detected after 15s, proceeding anyway")
        await asyncio.sleep(0.5)
        await self._screenshot("phone_sent")

    # ── Step 11: Optional comment → SUBMIT QUERY ──
    async def step_submit_comment(self):
        print("[Step 11] Submitting comment...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay(0.3, 0.5)

        submit_btn = None
        for attempt in range(15):
            try:
                btn = ctx.locator('button:has-text("SUBMIT QUERY"), button:has-text("SUBMIT"), button:has-text("Submit")').first
                if await btn.is_visible(timeout=1000):
                    submit_btn = btn
                    print("  [wait] SUBMIT QUERY button found")
                    break
            except Exception:
                pass
            await asyncio.sleep(1)

        if not submit_btn:
            print("  [warn] SUBMIT QUERY button not found after 15s, searching harder...")
            try:
                submit_btn = ctx.get_by_text("SUBMIT", exact=False).first
                await submit_btn.wait_for(state="visible", timeout=5000)
                print("  [wait] Found submit via get_by_text")
            except Exception:
                print("  [error] Cannot find SUBMIT QUERY button at all")

        if self.comment:
            try:
                textarea = ctx.locator("textarea:visible").first
                await textarea.wait_for(state="visible", timeout=5000)
                await textarea.fill(self.comment)
                print(f"  [fill] comment = '{self.comment[:50]}...'")
            except Exception:
                print("  [info] No comment textarea found, skipping comment text")
        else:
            print("  [info] No comment provided, skipping straight to SUBMIT QUERY")

        await self._screenshot("comment_filled")
        await self._random_delay(0.3, 0.5)

        clicked = False
        if submit_btn:
            try:
                await submit_btn.click()
                print("  [click] SUBMIT QUERY clicked")
                clicked = True
            except Exception:
                try:
                    await submit_btn.click(force=True)
                    print("  [click] SUBMIT QUERY force-clicked")
                    clicked = True
                except Exception:
                    pass

        if not clicked:
            selectors = [
                'button:has-text("SUBMIT QUERY")',
                'button:has-text("SUBMIT")',
                'button:has-text("Submit")',
            ]
            for sel in selectors:
                try:
                    btns = ctx.locator(sel)
                    count = await btns.count()
                    for i in range(count - 1, -1, -1):
                        b = btns.nth(i)
                        if await b.is_visible(timeout=2000):
                            await b.click()
                            print(f"  [click] SUBMIT QUERY clicked via {sel} (index {i})")
                            clicked = True
                            break
                    if clicked:
                        break
                except Exception:
                    continue

        if not clicked:
            raise Exception("Could not click SUBMIT QUERY button")

        await self._wait_for_new_content(ctx, min_wait=3, max_wait=15, expect_selector="input[type='file'], button:has-text('Select')")
        await self._random_delay(1, 2)
        await self._screenshot("comment_submitted")

    # ── Step 12: Upload documents (one at a time) ──
    async def _upload_single_file(self, ctx, doc_path):
        file_input = ctx.locator('input[type="file"]').first
        await file_input.wait_for(state="attached", timeout=15000)

        try:
            async with self.page.expect_file_chooser(timeout=10000) as fc_info:
                select_btn_selectors = [
                    'button:has-text("Select them")',
                    'button:has-text("Select")',
                    'button:has-text("Browse")',
                    'button:has-text("Upload")',
                    'button:has-text("Attach")',
                ]
                clicked = False
                for sel in select_btn_selectors:
                    try:
                        btn = ctx.locator(sel).first
                        if await btn.is_visible(timeout=2000):
                            await btn.click()
                            print(f"    [click] File select: {sel}")
                            clicked = True
                            break
                    except Exception:
                        continue
                if not clicked:
                    await file_input.dispatch_event("click")
                    print("    [click] Triggered file input directly")

            file_chooser = await fc_info.value
            await file_chooser.set_files(doc_path)
            return True
        except Exception as e:
            print(f"    [info] File chooser failed ({e}), trying direct input")
            try:
                await file_input.set_input_files(doc_path)
                return True
            except Exception as e2:
                print(f"    [error] Direct input also failed: {e2}")
                return False

    async def step_upload_documents(self):
        print(f"[Step 12] Uploading {len(self.document_paths)} document(s)...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay(0.3, 0.5)

        if not self.document_paths:
            print("  [info] No documents to upload")
            await self._screenshot("no_documents")
            return

        total_files = len(self.document_paths)

        for file_idx, doc_path in enumerate(self.document_paths):
            file_num = file_idx + 1
            is_last_file = (file_num == total_files)
            print(f"  [file {file_num}/{total_files}] Uploading: {doc_path}")

            uploaded = await self._upload_single_file(ctx, doc_path)
            if not uploaded:
                print(f"  [error] Failed to upload file {file_num}, skipping")
                continue

            print(f"  [file {file_num}/{total_files}] Upload complete")
            await self._screenshot(f"file_{file_num}_uploaded")

            for attempt in range(15):
                await asyncio.sleep(1)
                try:
                    yes_btn = ctx.locator('button:has-text("Yes, continue"), button:has-text("YES")').first
                    if await yes_btn.is_visible(timeout=1000):
                        print(f"  [wait] Confirmation buttons appeared")
                        break
                except Exception:
                    pass
            else:
                print(f"  [warn] Confirmation buttons not found after 15s")

            await self._random_delay(0.3, 0.5)

            if is_last_file:
                for txt in ["Yes, continue", "YES, CONTINUE", "Yes", "Continue"]:
                    try:
                        btn = ctx.locator(f'button:has-text("{txt}")').first
                        if await btn.is_visible(timeout=2000):
                            await btn.click()
                            print(f"  [click] Last file - clicked '{txt}'")
                            break
                    except Exception:
                        continue
            else:
                add_more_clicked = False
                for txt in ["No, add more documents", "No, add more", "NO, ADD MORE"]:
                    try:
                        btn = ctx.locator(f'button:has-text("{txt}")').first
                        if await btn.is_visible(timeout=2000):
                            await btn.click()
                            print(f"  [click] More files to go - clicked '{txt}'")
                            add_more_clicked = True
                            break
                    except Exception:
                        continue

                if not add_more_clicked:
                    print("  [warn] 'No, add more documents' button not found")

                for attempt in range(10):
                    await asyncio.sleep(1)
                    try:
                        fi = ctx.locator('input[type="file"]').first
                        await fi.wait_for(state="attached", timeout=1000)
                        print(f"  [wait] Ready for next file")
                        break
                    except Exception:
                        pass

        await self._screenshot("documents_uploaded")
        await self._random_delay(1, 2)

    # ── Step 13: Extract case number from confirmation ──
    async def step_get_confirmation(self):
        print("[Step 13] Getting confirmation and case number...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay(2, 4)
        await self._wait_for_new_content(ctx)

        try:
            page_text = await ctx.locator("body").text_content()
            patterns = [
                r"reference[:\s]+(\d+)",
                r"case number[:\s]*(\d+)",
                r"case[:\s]+(\d+)",
                r"processed under reference[:\s]+(\d+)",
                r"under reference[:\s]+(\d+)",
            ]
            for pattern in patterns:
                case_match = re.search(pattern, page_text, re.IGNORECASE)
                if case_match:
                    self.case_number = case_match.group(1)
                    print(f"  [info] Case number found: {self.case_number}")
                    break
            if not self.case_number:
                case_match = re.search(r"\b(\d{6,10})\b", page_text)
                if case_match:
                    self.case_number = case_match.group(1)
                    print(f"  [info] Possible case number: {self.case_number}")
        except Exception as e:
            print(f"  [warn] Could not extract case number: {e}")

        await self._screenshot("confirmation")

    # ── Step 14: Decline another refund → NO ──
    async def step_decline_another(self):
        print("[Step 14] Declining another refund (NO)...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay()

        for text in ["NO", "No", "no"]:
            try:
                await self._click_text(ctx, text)
                await self._screenshot("declined_another")
                await self._random_delay()
                return
            except Exception:
                continue
        print("  [info] No 'another refund' prompt found, skipping")
        await self._screenshot("final_state")

    async def run(self):
        print("=" * 60)
        print(f"Vueling Refund Bot - Job: {self.job_id}")
        print("=" * 60)
        print(f"  Booking Code  : {self.booking_code}")
        print(f"  Email         : {self.email}")
        print(f"  Reason        : {self.reason}")
        print(f"  Name          : {self.first_name} {self.surname}")
        print(f"  Contact Email : {self.contact_email}")
        print(f"  Phone         : {self.phone_prefix} {self.phone_number}")
        print(f"  Comment       : {self.comment[:50] if self.comment else 'None'}...")
        print(f"  Documents     : {len(self.document_paths)} file(s)")
        print(f"  Headless      : {self.headless}")
        print("=" * 60)

        result = {
            "success": False,
            "completed_steps": [],
            "case_number": None,
            "errors": [],
            "screenshots": [],
        }

        try:
            await self._run_step("Launch Browser", self.step_launch_browser, retries=2)
            await self._run_step("Navigate", self.step_navigate, retries=2)
            await self._run_step("Wait for Chatbot", self.step_wait_chatbot, retries=1)
            await self._run_step("Select CODE AND EMAIL", self.step_select_code_email, retries=2)
            await self._run_step("Fill Booking Details", self.step_fill_booking, retries=2)
            await self._run_step("Select Reason", self.step_select_reason, retries=3)
            await self._run_step("Confirm Documents", self.step_confirm_documents, retries=3)
            await self._run_step("Fill Name", self.step_fill_name, retries=2)
            await self._run_step("Contact Email", self.step_contact_email, retries=2)
            await self._run_step("Fill Phone", self.step_fill_phone, retries=2)
            await self._run_step("Submit Comment", self.step_submit_comment, retries=2)
            await self._run_step("Upload Documents", self.step_upload_documents, retries=2)
            await self._run_step("Get Confirmation", self.step_get_confirmation, retries=1)
            await self._run_step("Decline Another", self.step_decline_another, retries=1)

            result["success"] = True
            result["case_number"] = self.case_number

            print("\n" + "=" * 60)
            print(f"Bot completed all steps! Case: {self.case_number or 'unknown'}")
            print(f"Steps: {', '.join(self.completed_steps)}")
            print("=" * 60)

        except BotStepError as e:
            print(f"\n[ERROR] {e}")
            print(f"  Completed: {', '.join(self.completed_steps)}")
            result["errors"] = self.errors

        except Exception as e:
            print(f"\n[ERROR] Unexpected: {e}")
            traceback.print_exc()
            try:
                await self._screenshot("unexpected_error")
            except Exception:
                pass
            result["errors"].append({"step": "unknown", "error": str(e)})

        finally:
            result["completed_steps"] = self.completed_steps
            screenshots_dir = Path(self.screenshots_dir)
            if screenshots_dir.exists():
                result["screenshots"] = sorted([str(p) for p in screenshots_dir.glob("*.png")])

            try:
                if self.browser:
                    await self.browser.close()
            except Exception:
                pass
            try:
                if hasattr(self, "pw_cm"):
                    await self.pw_cm.__aexit__(None, None, None)
            except Exception:
                pass

        return result
