import asyncio
import os
import random
import re
import shutil
import traceback
from pathlib import Path

from playwright.async_api import async_playwright, Page, Frame
from playwright_stealth import Stealth

import config


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
        phone_country=None,
        phone_number=None,
        comment=None,
        document_paths=None,
        headless=None,
        job_id=None,
        on_progress=None,
    ):
        self.booking_code = booking_code or config.BOOKING_CODE
        self.email = email or config.EMAIL
        self.reason = reason or config.REASON
        self.first_name = first_name or ""
        self.surname = surname or ""
        self.contact_email = contact_email or ""
        self.phone_country = phone_country or "+92"
        self.phone_number = phone_number or ""
        self.comment = comment if comment else ""
        self.document_paths = document_paths or []
        self.headless = headless if headless is not None else config.HEADLESS
        self.job_id = job_id or "manual"
        self.on_progress = on_progress
        self.browser = None
        self.page = None
        self.step_count = 0
        self.completed_steps = []
        self.errors = []
        self.case_number = None

        self.screenshots_dir = os.path.join(config.SCREENSHOTS_DIR, self.job_id)
        os.makedirs(self.screenshots_dir, exist_ok=True)

    def _notify_progress(self):
        if self.on_progress:
            screenshots_dir = Path(self.screenshots_dir)
            screenshots = sorted([str(p) for p in screenshots_dir.glob("*.png")]) if screenshots_dir.exists() else []
            self.on_progress(
                completed_steps=list(self.completed_steps),
                errors=list(self.errors),
                screenshots=screenshots,
                case_number=self.case_number,
            )

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
                self._notify_progress()
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
                    self._notify_progress()
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
        await self._random_delay()

        for text in ["CODE AND EMAIL", "Code and email", "code and email", "code"]:
            try:
                await self._click_text(ctx, text)
                await self._screenshot("code_email_selected")
                await self._wait_for_new_content(ctx, expect_selector="input:visible")
                await self._random_delay()
                return
            except Exception:
                continue
        raise Exception("Could not find 'CODE AND EMAIL' option")

    # ── Step 5: Fill booking code + email → SEND ──
    async def step_fill_booking(self):
        print("[Step 5] Filling booking details...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay()

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

        await self._random_delay(0.5, 1.5)

        try:
            await self._fill_input(ctx, "email", self.email)
        except Exception:
            inputs = ctx.locator("input:visible")
            count = await inputs.count()
            if count >= 2:
                await inputs.nth(1).fill(self.email)
                print(f"  [fill] second input = '{self.email}'")

        await self._screenshot("booking_filled")
        await self._random_delay()

        for text in ["SEND", "Send", "send", "Enviar"]:
            try:
                await self._click_text(ctx, text)
                break
            except Exception:
                continue

        await self._screenshot("send_clicked")
        print("  Waiting for booking verification...")
        await self._wait_for_new_content(ctx, min_wait=3, max_wait=12)
        await self._random_delay(2, 4)
        await self._screenshot("verification_response")

    # ── Step 6: Select cancellation reason ──
    async def step_select_reason(self):
        print(f"[Step 6] Selecting reason: {self.reason}...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay()
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
                await self._wait_for_new_content(ctx)
                await self._random_delay()
                return
            except Exception:
                continue
        raise Exception(f"Could not find reason: '{self.reason}'")

    # ── Step 7: "Got all your documents to hand?" → YES ──
    async def step_confirm_documents(self):
        print("[Step 7] Confirming documents ready (YES)...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay(2, 4)
        await self._wait_for_new_content(ctx)

        for text in ["YES", "Yes", "yes"]:
            try:
                await self._click_text(ctx, text)
                await self._screenshot("documents_confirmed")
                await self._wait_for_new_content(ctx)
                await self._random_delay()
                return
            except Exception:
                continue
        raise Exception("Could not find YES button")

    # ── Step 8: Enter first name + surname → SEND ──
    async def step_fill_name(self):
        print(f"[Step 8] Filling name: {self.first_name} {self.surname}...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay()
        await self._wait_for_new_content(ctx, min_wait=2, max_wait=8)

        try:
            await self._fill_input(ctx, "First name", self.first_name)
        except Exception:
            try:
                await self._fill_input(ctx, "first", self.first_name)
            except Exception:
                inputs = ctx.locator("input:visible")
                await inputs.first.fill(self.first_name)
                print(f"  [fill] first input = '{self.first_name}'")

        await self._random_delay(0.3, 0.8)

        try:
            await self._fill_input(ctx, "Surname", self.surname)
        except Exception:
            try:
                await self._fill_input(ctx, "surname", self.surname)
            except Exception:
                inputs = ctx.locator("input:visible")
                count = await inputs.count()
                if count >= 2:
                    await inputs.nth(1).fill(self.surname)
                    print(f"  [fill] second input = '{self.surname}'")

        await self._screenshot("name_filled")
        await self._random_delay()

        for text in ["SEND", "Send"]:
            try:
                await self._click_text(ctx, text)
                break
            except Exception:
                continue

        await self._wait_for_new_content(ctx, min_wait=3, max_wait=10)
        await self._random_delay()
        await self._screenshot("name_sent")

    # ── Step 9: Enter contact email (type in chat) ──
    async def step_contact_email(self):
        print(f"[Step 9] Entering contact email: {self.contact_email}...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay()
        await self._wait_for_new_content(ctx)

        await self._type_in_chat(ctx, self.contact_email)
        await self._screenshot("contact_email_sent")
        await self._wait_for_new_content(ctx, min_wait=3, max_wait=12, expect_selector='text="Choose a prefix", input[type="tel"]:visible, select:visible')
        await self._random_delay(2, 4)

    # ── Step 10: Enter phone country + number → SEND ──
    async def step_fill_phone(self):
        print(f"[Step 10] Filling phone: {self.phone_country} {self.phone_number}...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay(2, 4)
        await self._wait_for_new_content(ctx, min_wait=3, max_wait=12)
        await self._screenshot("phone_step_ready")

        country_selected = False
        prefix = self.phone_country.lstrip("+")

        dropdown_trigger_selectors = [
            'text="Choose a prefix"',
            '[class*="prefix"]:visible',
            '[class*="country"]:visible',
            '[class*="dropdown"]:visible',
            '[class*="select"]:visible',
        ]
        for sel in dropdown_trigger_selectors:
            try:
                trigger = ctx.locator(sel).first
                await trigger.wait_for(state="visible", timeout=10000)
                await trigger.click()
                print(f"  [click] Opened prefix dropdown via: {sel}")
                await self._random_delay(1, 2)
                await self._screenshot("prefix_dropdown_opened")

                search_patterns = [f"(+{prefix})", f"+{prefix}"]
                for pattern in search_patterns:
                    try:
                        option = ctx.get_by_text(pattern, exact=False).first
                        await option.wait_for(state="visible", timeout=5000)
                        await option.click()
                        opt_text = await option.text_content() or pattern
                        print(f"  [select] Country prefix: {opt_text.strip()}")
                        country_selected = True
                        break
                    except Exception:
                        continue

                if country_selected:
                    break

                all_options = ctx.locator('[class*="option"]:visible, li:visible, [role="option"]:visible')
                count = await all_options.count()
                for i in range(count):
                    opt = all_options.nth(i)
                    text = await opt.text_content() or ""
                    if f"(+{prefix})" in text or f"+{prefix}" in text:
                        await opt.click()
                        print(f"  [select] Country prefix (scan): {text.strip()}")
                        country_selected = True
                        break

                if country_selected:
                    break

            except Exception as e:
                print(f"  [info] Dropdown trigger '{sel}' not found: {e}")
                continue

        if not country_selected:
            try:
                native_select = ctx.locator("select:visible:not([disabled])").first
                await native_select.wait_for(state="visible", timeout=5000)
                options = await native_select.locator("option").all()
                for option in options:
                    opt_text = await option.text_content() or ""
                    opt_val = await option.get_attribute("value") or ""
                    if f"(+{prefix})" in opt_text or f"+{prefix}" in opt_val or opt_val == prefix:
                        await native_select.select_option(value=opt_val)
                        print(f"  [select] Country code (native): {opt_text.strip()}")
                        country_selected = True
                        break
            except Exception:
                pass

        if not country_selected:
            print(f"  [warn] Could not select country prefix +{prefix}, proceeding with default")

        await self._random_delay(0.5, 1)
        await self._screenshot("prefix_selected")

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
                await phone_input.fill(self.phone_number)
                print(f"  [fill] phone input via '{sel}' = '{self.phone_number}'")
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
        await self._random_delay()

        for text in ["SEND", "Send"]:
            try:
                await self._click_text(ctx, text)
                break
            except Exception:
                continue

        await self._wait_for_new_content(ctx, min_wait=3, max_wait=10)
        await self._random_delay()
        await self._screenshot("phone_sent")

    # ── Step 11: Optional comment → SUBMIT QUERY ──
    async def step_submit_comment(self):
        print("[Step 11] Submitting comment...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay()
        await self._wait_for_new_content(ctx)

        if self.comment:
            try:
                textarea = ctx.locator("textarea:visible").first
                await textarea.wait_for(state="visible", timeout=10000)
                await textarea.fill(self.comment)
                print(f"  [fill] comment = '{self.comment[:50]}...'")
            except Exception:
                print("  [info] No comment textarea found, skipping comment text")
        else:
            print("  [info] No comment provided, leaving textarea empty")

        await self._screenshot("comment_filled")
        await self._random_delay()

        for text in ["SUBMIT QUERY", "Submit query", "SUBMIT", "Submit"]:
            try:
                await self._click_text(ctx, text)
                print(f"  [click] Submit: '{text}'")
                break
            except Exception:
                continue

        await self._wait_for_new_content(ctx, min_wait=3, max_wait=12, expect_selector="input[type='file'], button:has-text('Select')")
        await self._random_delay(2, 4)
        await self._screenshot("comment_submitted")

    # ── Step 12: Upload documents ──
    async def step_upload_documents(self):
        print(f"[Step 12] Uploading {len(self.document_paths)} document(s)...")
        ctx = await self._find_chatbot_frame()
        await self._random_delay()
        await self._wait_for_new_content(ctx)

        if not self.document_paths:
            print("  [info] No documents to upload")
            await self._screenshot("no_documents")
            return

        try:
            file_input = ctx.locator('input[type="file"]').first
            await file_input.wait_for(state="attached", timeout=10000)

            try:
                async with self.page.expect_file_chooser(timeout=10000) as fc_info:
                    select_btn_selectors = [
                        'button:has-text("Select them")',
                        'button:has-text("Select")',
                        'button:has-text("Browse")',
                        'button:has-text("Upload")',
                        'button:has-text("Attach")',
                        '[class*="upload"] button',
                        '[class*="attach"] button',
                    ]
                    clicked = False
                    for sel in select_btn_selectors:
                        try:
                            btn = ctx.locator(sel).first
                            if await btn.is_visible(timeout=2000):
                                await btn.click()
                                print(f"  [click] File select button: {sel}")
                                clicked = True
                                break
                        except Exception:
                            continue
                    if not clicked:
                        await file_input.dispatch_event("click")
                        print("  [click] Triggered file input click directly")

                file_chooser = await fc_info.value
                await file_chooser.set_files(self.document_paths)
                print(f"  [upload] {len(self.document_paths)} file(s) uploaded via file chooser")
            except Exception as e_chooser:
                print(f"  [info] File chooser method failed ({e_chooser}), trying direct set_input_files")
                await file_input.set_input_files(self.document_paths)
                print(f"  [upload] {len(self.document_paths)} file(s) uploaded via direct input")

        except Exception as e:
            print(f"  [warn] Primary upload failed: {e}")
            try:
                for doc_path in self.document_paths:
                    async with self.page.expect_file_chooser(timeout=10000) as fc_info:
                        for sel in ['button:has-text("Select them")', 'button:has-text("Select")', 'button:has-text("Upload")', '[class*="upload"]']:
                            try:
                                btn = ctx.locator(sel).first
                                if await btn.is_visible(timeout=2000):
                                    await btn.click()
                                    break
                            except Exception:
                                continue
                    file_chooser = await fc_info.value
                    await file_chooser.set_files(doc_path)
                    print(f"  [upload] File uploaded via chooser: {doc_path}")
                    await self._random_delay(0.5, 1)
            except Exception as e2:
                raise Exception(f"File upload failed: {e2}")

        await self._random_delay(2, 3)
        await self._screenshot("documents_uploaded")
        await self._wait_for_new_content(ctx)
        await self._random_delay()

        for confirm_text in ["Yes, continue", "YES, CONTINUE", "Yes", "Continue"]:
            try:
                confirm_btn = ctx.locator(f'button:has-text("{confirm_text}")').first
                await confirm_btn.wait_for(state="visible", timeout=5000)
                await confirm_btn.click()
                print(f"  [click] Document confirmation: '{confirm_text}'")
                await self._random_delay(1, 2)
                await self._screenshot("documents_confirmed")
                break
            except Exception:
                continue

        await self._wait_for_new_content(ctx)
        await self._random_delay()

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
        print(f"  Phone         : {self.phone_country} {self.phone_number}")
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
