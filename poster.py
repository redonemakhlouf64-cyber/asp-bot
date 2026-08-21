#!/usr/bin/env python3
"""
poster.py - Facebook Auto Poster v7.0
Cookies-only. No email, no password, no proxy.
"""

import os
import json
import time
import random
import sys
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


def log(msg):
    print(f"[poster] {msg}", flush=True)


def _normalize_cookies(cookies):
    """Convert browser cookies (Firefox/Chrome export) to Playwright format."""
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


# --- Config (cookies-only) ---
ACC_NUM = int(os.environ.get("ACCOUNT_NUM", "1"))
FORCE_ALL = os.environ.get("FORCE_ALL", "false").lower() == "true"
CONTENT_RAW = os.environ.get("CONTENT", "").strip()
FB_COOKIES = os.environ.get(f"FB_COOKIES_{ACC_NUM}", "").strip()

DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0.0.0 Safari/537.36")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
window.chrome = {runtime: {}};
"""


def get_content():
    if CONTENT_RAW:
        try:
            items = json.loads(CONTENT_RAW)
            if isinstance(items, list) and items:
                return random.choice(items)
            if isinstance(items, str):
                return items
        except Exception:
            return CONTENT_RAW
    return "Check out my latest eBooks collection! 📚✨"


def snapshot(page, label):
    """Save screenshot + HTML for debugging."""
    try:
        page.screenshot(path=f"debug_{label}.png", full_page=True)
        log(f"📸 Saved screenshot: debug_{label}.png")
    except Exception as e:
        log(f"screenshot fail: {e}")
    try:
        html = page.content()[:2000]
        log(f"📄 HTML head [{label}]: {html[:500]}")
    except Exception:
        pass


def verify_login(page):
    """Step 1: Verify cookies actually logged us in."""
    log("STEP 1/3: Verify session with cookies")
    try:
        page.goto("https://www.facebook.com/",
                  wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log(f"❌ goto failed: {e}")
        return False
    time.sleep(random.uniform(4, 6))

    url = page.url
    title = page.title()
    log(f"URL: {url}")
    log(f"Title: {title}")

    if "login" in url.lower() or "checkpoint" in url.lower():
        log("❌ Redirected to login/checkpoint → cookies invalid")
        snapshot(page, "01_login_redirect")
        return False

    cookies_now = page.context.cookies()
    c_user = next((c for c in cookies_now if c.get("name") == "c_user"), None)
    if not c_user:
        log("❌ Missing c_user cookie after navigation")
        snapshot(page, "01_no_cuser")
        return False

    log(f"✅ Logged in as user id: {c_user.get('value')}")
    return True


def open_composer(page):
    """Step 2: Open 'What's on your mind' composer."""
    log("STEP 2/3: Open composer")
    composer_selectors = [
        'span:has-text("What\'s on your mind")',
        'span:has-text("What\'s on your mind, ")',
        'div[role="button"]:has-text("What\'s on your mind")',
        '[aria-label*="Create a post"]',
        '[aria-label*="What\'s on your mind"]',
    ]
    for sel in composer_selectors:
        try:
            page.locator(sel).first.click(timeout=8000)
            log(f"✅ Composer opened: {sel}")
            time.sleep(random.uniform(2, 4))
            return True
        except Exception:
            continue

    log("❌ Could not open composer with any selector")
    snapshot(page, "02_no_composer")
    return False


def publish_post(page):
    """Step 3: Type text and click Post."""
    log("STEP 3/3: Type content and publish")
    text = get_content()
    log(f"Content: {text[:100]}")

    try:
        editor = page.locator(
            'div[contenteditable="true"][role="textbox"]').first
        editor.click(timeout=10000)
        time.sleep(1)
        editor.type(text, delay=random.randint(30, 80))
        log("✅ Typed content into editor")
    except Exception as e:
        log(f"❌ Type failed: {e}")
        snapshot(page, "03_type_fail")
        return False

    time.sleep(random.uniform(3, 5))

    for sel in [
        'div[aria-label="Post"][role="button"]',
        'div[aria-label="Post"]',
        'button:has-text("Post")',
    ]:
        try:
            page.locator(sel).first.click(timeout=8000)
            log(f"✅ Clicked Post button: {sel}")
            time.sleep(random.uniform(6, 10))
            log("🎉 Post submitted")
            return True
        except Exception:
            continue

    log("❌ Could not click Post button")
    snapshot(page, "03_no_post_btn")
    return False


def main():
    log("=" * 50)
    log(f"poster.py v7.0 (cookies-only) START | Acc #{ACC_NUM}")
    log("=" * 50)

    if not FB_COOKIES:
        log(f"❌ FB_COOKIES_{ACC_NUM} secret is empty. Nothing to do.")
        return 1

    try:
        cookies_raw = json.loads(FB_COOKIES)
    except Exception as e:
        log(f"❌ FB_COOKIES_{ACC_NUM} invalid JSON: {e}")
        return 1

    cookies = _normalize_cookies(cookies_raw)
    log(f"🍪 Loaded {len(cookies)} cookies")

    success = False
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
            if not publish_post(page):
                return 1

            success = True
        except Exception as e:
            log(f"❌ Fatal error: {e}")
            try:
                snapshot(page, "99_fatal")
            except Exception:
                pass
        finally:
            browser.close()

    log("=" * 50)
    log(f"poster.py END | {'✅ SUCCESS' if success else '❌ FAILURE'}")
    log("=" * 50)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
