#!/usr/bin/env python3
"""
poster.py v7.2 - Facebook Poster (Cookies-Only, Desktop www)
Uses the same proven pattern as discover.py which succeeded.
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

FB_HOME = "https://www.facebook.com/"

# Desktop UA (same as discover.py which worked)
DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0.0.0 Safari/537.36")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
window.chrome = {runtime: {}};
"""


def pick_content():
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
    log("STEP 1/3: Verify session with cookies")
    try:
        page.goto(FB_HOME, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log("❌ goto failed: " + str(e))
        return False
    time.sleep(random.uniform(4, 6))

    url = page.url
    log("URL: " + url)

    if "login" in url.lower() or "checkpoint" in url.lower():
        log("❌ Redirected to login/checkpoint")
        snapshot(page, "01_login_redirect")
        return False

    cookies_now = page.context.cookies()
    c_user = next((c for c in cookies_now if c.get("name") == "c_user"), None)
    if not c_user:
        log("❌ Missing c_user after navigation")
        snapshot(page, "01_no_cuser")
        return False

    log("✅ Logged in as user id: " + str(c_user.get("value")))
    return True


def open_composer(page):
    log("STEP 2/3: Open composer on home feed")
    # Find and click composer trigger (What's on your mind?)
    triggers = [
        "div[role='button']:has-text(\"What's on your mind\")",
        "div[role='button']:has-text('What\u2019s on your mind')",
        "[aria-label*=\"What's on your mind\"]",
        "div[role='textbox']",
    ]
    opened = False
    for sel in triggers:
        try:
            btn = page.locator(sel).first
            btn.wait_for(state="visible", timeout=8000)
            btn.click()
            time.sleep(random.uniform(2, 4))
            opened = True
            log("✅ Composer trigger clicked: " + sel)
            break
        except Exception:
            continue
    if not opened:
        log("❌ Could not find composer trigger")
        snapshot(page, "02_no_composer_trigger")
        return False

    # Wait for the composer dialog
    dialog_sels = [
        "div[role='dialog']",
        "[aria-label='Create post']",
        "[aria-label='Create Post']",
    ]
    for sel in dialog_sels:
        try:
            page.locator(sel).first.wait_for(state="visible", timeout=8000)
            log("✅ Composer dialog visible: " + sel)
            return True
        except Exception:
            continue
    log("⚠️  Composer dialog not detected, continuing anyway")
    snapshot(page, "02_composer_state")
    return True


def publish_post(page, text):
    log("STEP 3/3: Type content and publish")
    if not text:
        log("❌ No content to post (CONTENT secret empty)")
        return False

    # Find textbox inside dialog
    textbox_sels = [
        "div[role='dialog'] div[role='textbox']",
        "div[role='dialog'] [contenteditable='true']",
        "div[role='textbox'][contenteditable='true']",
    ]
    typed = False
    for sel in textbox_sels:
        try:
            tb = page.locator(sel).first
            tb.wait_for(state="visible", timeout=8000)
            tb.click()
            time.sleep(1)
            tb.type(text, delay=random.randint(20, 60))
            time.sleep(random.uniform(1.5, 3))
            typed = True
            log("✅ Content typed (" + str(len(text)) + " chars) via " + sel)
            break
        except Exception:
            continue
    if not typed:
        log("❌ Could not find textbox")
        snapshot(page, "03_no_textbox")
        return False

    snapshot(page, "03_before_post")

    # Click Post button
    post_sels = [
        "div[role='dialog'] div[role='button'][aria-label='Post']",
        "div[aria-label='Post'][role='button']",
        "div[role='dialog'] div[role='button']:has-text('Post')",
    ]
    posted = False
    for sel in post_sels:
        try:
            btn = page.locator(sel).first
            btn.wait_for(state="visible", timeout=8000)
            btn.click()
            posted = True
            log("✅ Post button clicked: " + sel)
            break
        except Exception:
            continue
    if not posted:
        log("❌ Could not click Post button")
        snapshot(page, "03_no_post_button")
        return False

    # Wait for dialog to close (success indicator)
    time.sleep(random.uniform(5, 8))
    snapshot(page, "04_after_post")

    try:
        page.locator("div[role='dialog']").first.wait_for(
            state="detached", timeout=15000)
        log("✅ Composer closed — post published!")
        return True
    except Exception:
        log("⚠️  Composer still open after post click. Check screenshot.")
        return False


def run():
    log("=" * 50)
    log("poster.py v7.2 (cookies-only, desktop www)")
    log("Account: #" + str(ACC_NUM) + " | force_all=" + str(FORCE_ALL))
    log("=" * 50)

    if not FB_COOKIES:
        log("❌ FB_COOKIES_" + str(ACC_NUM) + " not set")
        return 1

    try:
        cookies_raw = json.loads(FB_COOKIES)
    except Exception as e:
        log("❌ FB_COOKIES invalid JSON: " + str(e))
        return 1

    has_c_user = any(c.get("name") == "c_user" for c in cookies_raw)
    has_xs = any(c.get("name") == "xs" for c in cookies_raw)
    log("🔍 c_user present: " + str(has_c_user) + " | xs present: " + str(has_xs))
    if not has_c_user or not has_xs:
        log("❌ Missing essential cookies (c_user or xs)")
        return 1

    cookies = _normalize_cookies(cookies_raw)
    log("🍪 Loaded " + str(len(cookies)) + " cookies")

    content = pick_content()
    if not content:
        log("❌ No content to post — set CONTENT secret")
        return 1
    log("📝 Content preview: " + content[:80].replace("\n", " ") + ("..." if len(content) > 80 else ""))

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
                user_agent=DESKTOP_UA,
                viewport={"width": 1366, "height": 768},
                locale="en-US",
            )
            context.add_init_script(STEALTH_JS)
            context.add_cookies(cookies)
            page = context.new_page()

            if not verify_login(page):
                return 1
            if not open_composer(page):
                return 1
            if not publish_post(page, content):
                return 1

            log("=" * 50)
            log("🎉 SUCCESS — post published for account #" + str(ACC_NUM))
            log("=" * 50)
            return 0
        finally:
            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(run())
