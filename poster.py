#!/usr/bin/env python3
"""
poster.py v7.1 - Facebook Poster (Cookies-Only, Mobile UA)
Cookies come from Kiwi Browser on mobile, so we use mobile UA to match.
"""

import os
import json
import time
import random
import sys
from playwright.sync_api import sync_playwright


def log(msg):
    print("[poster] " + str(msg), flush=True)


def snapshot(page, name):
    try:
        page.screenshot(path="debug_" + name + ".png", full_page=True)
        log("📸 Saved screenshot: debug_" + name + ".png")
    except Exception as e:
        log("snapshot error: " + str(e))
    try:
        html = page.content()[:1500]
        log("📄 HTML head " + name + ": " + html)
    except Exception:
        pass


def _normalize_cookies(cookies):
    ss_map = {"lax": "Lax", "strict": "Strict",
              "none": "None", "no_restriction": "None"}
    allowed = {"name", "value", "domain", "path", "expires",
               "httpOnly", "secure", "sameSite"}
    out = []
    for c in cookies:
        nc = {}
        for k, v in c.items():
            if k == "expirationDate":
                nc["expires"] = float(v) if v is not None else -1
            elif k == "sameSite":
                nc["sameSite"] = ss_map.get(str(v).lower(), "Lax") if v else "Lax"
            elif k in allowed:
                nc[k] = v
        nc.setdefault("sameSite", "Lax")
        nc.setdefault("path", "/")
        if "domain" not in nc:
            continue
        out.append(nc)
    return out


# --- Config ---
ACC_NUM = int(os.environ.get("ACCOUNT_NUM", "1"))
FB_COOKIES = os.environ.get("FB_COOKIES_" + str(ACC_NUM), "").strip()
CONTENT_RAW = os.environ.get("CONTENT", "").strip()
FORCE_ALL = os.environ.get("FORCE_ALL", "").lower() in ("true", "1", "yes")

FB_HOME = "https://m.facebook.com/"

# Mobile UA matching Kiwi Browser (Chromium-based Android)
MOBILE_UA = ("Mozilla/5.0 (Linux; Android 13; SM-G998B) "
             "AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/120.0.0.0 Mobile Safari/537.36")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
window.chrome = {runtime: {}};
"""


def get_content():
    if not CONTENT_RAW:
        return ""
    try:
        data = json.loads(CONTENT_RAW)
        if isinstance(data, list) and data:
            return random.choice(data)
        if isinstance(data, str):
            return data
    except Exception:
        pass
    return CONTENT_RAW


def verify_login(page):
    log("STEP 1/3: Verify session")
    try:
        page.goto(FB_HOME, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log("❌ goto failed: " + str(e))
        return False
    time.sleep(random.uniform(4, 6))

    url = page.url
    title = page.title()
    log("URL: " + url)
    log("Title: " + title)

    if "login" in url.lower() or "checkpoint" in url.lower():
        log("❌ Redirected to login/checkpoint")
        snapshot(page, "01_login_redirect")
        return False

    cookies_now = page.context.cookies()
    log("📊 Cookies in context now: " + str(len(cookies_now)))
    c_user = next((c for c in cookies_now if c.get("name") == "c_user"), None)
    if not c_user:
        log("❌ Missing c_user cookie after navigation")
        snapshot(page, "01_no_cuser")
        return False

    log("✅ Logged in as user id: " + str(c_user.get("value")))
    return True


def open_composer(page):
    log("STEP 2/3: Open composer")
    # Mobile FB composer opens from the "What's on your mind?" trigger
    try:
        # Try multiple selectors for mobile composer trigger
        selectors = [
            'div[role="button"]:has-text("What")',
            'a[href*="/composer/"]',
            'div[aria-label*="Create"]',
            'div[role="button"][tabindex="0"]',
        ]
        clicked = False
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=3000):
                    el.click()
                    clicked = True
                    log("  clicked selector: " + sel)
                    break
            except Exception:
                continue

        if not clicked:
            log("❌ Composer trigger not found")
            snapshot(page, "02_no_composer")
            return False

        time.sleep(random.uniform(3, 5))
        log("✅ Composer opened")
        return True
    except Exception as e:
        log("❌ open_composer error: " + str(e))
        snapshot(page, "02_composer_error")
        return False


def publish_post(page, text):
    log("STEP 3/3: Publish post")
    if not text:
        log("❌ No content to post")
        return False

    # Type into composer textarea
    try:
        textarea_selectors = [
            'textarea',
            'div[contenteditable="true"]',
            'div[role="textbox"]',
        ]
        typed = False
        for sel in textarea_selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=3000):
                    el.click()
                    el.type(text, delay=random.randint(30, 80))
                    typed = True
                    log("  typed into: " + sel)
                    break
            except Exception:
                continue

        if not typed:
            log("❌ Failed to type content")
            snapshot(page, "03_type_fail")
            return False

        time.sleep(random.uniform(2, 4))

        # Click Post button
        post_selectors = [
            'div[role="button"]:has-text("Post")',
            'button:has-text("Post")',
            'div[aria-label="Post"]',
        ]
        posted = False
        for sel in post_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=3000):
                    btn.click()
                    posted = True
                    log("  clicked Post: " + sel)
                    break
            except Exception:
                continue

        if not posted:
            log("❌ Post button not found")
            snapshot(page, "03_no_post_btn")
            return False

        time.sleep(random.uniform(5, 8))
        log("✅ Post published")
        return True
    except Exception as e:
        log("❌ publish error: " + str(e))
        snapshot(page, "03_publish_error")
        return False


def main():
    log("=" * 50)
    log("poster.py v7.1 (cookies-only, mobile UA) | Acc #" + str(ACC_NUM))
    log("=" * 50)

    if not FB_COOKIES:
        log("❌ FB_COOKIES_" + str(ACC_NUM) + " is empty")
        return 1

    try:
        cookies_raw = json.loads(FB_COOKIES)
    except Exception as e:
        log("❌ FB_COOKIES invalid JSON: " + str(e))
        return 1

    cookies = _normalize_cookies(cookies_raw)
    log("🍪 Loaded " + str(len(cookies)) + " cookies")

    text = get_content()
    if text:
        log("📝 Content preview: " + text[:80])

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        try:
            context = browser.new_context(
                user_agent=MOBILE_UA,
                viewport={"width": 412, "height": 915},
                device_scale_factor=2.6,
                is_mobile=True,
                has_touch=True,
                locale="en-US",
            )
            context.add_init_script(STEALTH_JS)
            context.add_cookies(cookies)
            page = context.new_page()

            try:
                if not verify_login(page):
                    return 1

                if not open_composer(page):
                    return 1

                if not publish_post(page, text):
                    return 1

                log("🎉 SUCCESS")
                return 0
            except Exception as e:
                log("❌ fatal: " + str(e))
                snapshot(page, "99_fatal")
                return 1
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
