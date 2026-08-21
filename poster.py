#!/usr/bin/env python3
"""
poster.py v7.3 - Facebook Poster via mbasic.facebook.com
Uses the basic HTML version of Facebook for bulletproof posting.
No JavaScript, no React, no CSS shenanigans.
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

# Use mbasic (basic HTML) for reliable posting
MBASIC_HOME = "https://mbasic.facebook.com/"
MBASIC_COMPOSER = "https://mbasic.facebook.com/composer/mbasic/"

# Use a mobile UA for mbasic (it's the mobile basic version)
MBASIC_UA = ("Mozilla/5.0 (Linux; Android 10; SM-G970F) "
             "AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/120.0.0.0 Mobile Safari/537.36")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
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
    log("STEP 1/3: Verify session on mbasic.facebook.com")
    try:
        page.goto(MBASIC_HOME, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log("❌ goto failed: " + str(e))
        return False
    time.sleep(random.uniform(3, 5))

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
    log("STEP 2/3: Navigate to mbasic composer")
    try:
        page.goto(MBASIC_COMPOSER, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log("❌ composer goto failed: " + str(e))
        return False
    time.sleep(random.uniform(2, 4))

    url = page.url
    log("Composer URL: " + url)

    if "login" in url.lower():
        log("❌ Composer redirected to login")
        snapshot(page, "02_composer_login")
        return False

    # Check for the textarea
    textarea_sels = [
        "textarea[name='xc_message']",
        "textarea[placeholder*=\"What's on your mind\"]",
        "textarea",
    ]
    for sel in textarea_sels:
        try:
            ta = page.locator(sel).first
            ta.wait_for(state="visible", timeout=8000)
            log("✅ Composer textarea found: " + sel)
            return True
        except Exception:
            continue

    log("❌ No textarea on composer page")
    snapshot(page, "02_no_textarea")
    return False


def publish_post(page, text):
    log("STEP 3/3: Type content and submit")
    if not text:
        log("❌ No content")
        return False

    # Fill the textarea
    textarea_sels = [
        "textarea[name='xc_message']",
        "textarea[placeholder*=\"What's on your mind\"]",
        "textarea",
    ]
    filled = False
    for sel in textarea_sels:
        try:
            ta = page.locator(sel).first
            ta.wait_for(state="visible", timeout=5000)
            ta.fill(text)
            filled = True
            log("✅ Content filled (" + str(len(text)) + " chars) via " + sel)
            break
        except Exception:
            continue
    if not filled:
        log("❌ Could not fill textarea")
        snapshot(page, "03_no_textarea_fill")
        return False

    time.sleep(random.uniform(1, 2))
    snapshot(page, "03_before_submit")

    # Click submit (Post button)
    submit_sels = [
        "input[type='submit'][name='view_post']",
        "input[type='submit'][value='Post']",
        "input[type='submit']",
        "button[type='submit']",
    ]
    submitted = False
    for sel in submit_sels:
        try:
            btn = page.locator(sel).first
            btn.wait_for(state="visible", timeout=5000)
            btn.click()
            submitted = True
            log("✅ Submit clicked: " + sel)
            break
        except Exception:
            continue
    if not submitted:
        log("❌ Could not click submit")
        snapshot(page, "03_no_submit")
        return False

    # Wait for redirect back to home (success indicator)
    time.sleep(random.uniform(4, 6))
    snapshot(page, "04_after_submit")

    final_url = page.url
    log("Final URL: " + final_url)

    if "composer" in final_url.lower():
        log("⚠️  Still on composer page — post may have failed")
        # Check for error messages
        try:
            body_text = page.locator("body").inner_text()[:500]
            log("Page text: " + body_text.replace("\n", " | "))
        except Exception:
            pass
        return False

    log("✅ Redirected away from composer — post published!")
    return True


def run():
    log("=" * 50)
    log("poster.py v7.3 (mbasic.facebook.com - bulletproof)")
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
        log("❌ Missing essential cookies")
        return 1

    cookies = _normalize_cookies(cookies_raw)
    log("🍪 Loaded " + str(len(cookies)) + " cookies")

    content = pick_content()
    if not content:
        log("❌ No content — set CONTENT secret")
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
                user_agent=MBASIC_UA,
                viewport={"width": 412, "height": 915},
                is_mobile=True,
                has_touch=True,
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
