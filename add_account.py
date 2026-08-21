#!/usr/bin/env python3
"""
add_account.py v7.1 - Cookies-Only Verifier (Mobile UA)
Matches Kiwi Browser mobile origin of the cookies.
"""

import os
import json
import time
import sys
from playwright.sync_api import sync_playwright


def log(msg):
    print("[add_account] " + str(msg), flush=True)


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


FB_HOME = "https://m.facebook.com/"

# Mobile UA matching Kiwi Browser
MOBILE_UA = ("Mozilla/5.0 (Linux; Android 13; SM-G998B) "
             "AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/120.0.0.0 Mobile Safari/537.36")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
window.chrome = {runtime: {}};
"""


def verify_account(acc_num):
    """Verify cookies for a single account. Returns True/False/None."""
    log("--- Verifying account #" + str(acc_num) + " ---")
    fb_cookies = os.environ.get("FB_COOKIES_" + str(acc_num), "").strip()
    if not fb_cookies:
        log("⏭️  FB_COOKIES_" + str(acc_num) + " not set. Skipping.")
        return None

    try:
        cookies_raw = json.loads(fb_cookies)
    except Exception as e:
        log("❌ FB_COOKIES_" + str(acc_num) + " invalid JSON: " + str(e))
        return False

    has_c_user = any(c.get("name") == "c_user" for c in cookies_raw)
    has_xs = any(c.get("name") == "xs" for c in cookies_raw)
    log("🔍 c_user present: " + str(has_c_user) + " | xs present: " + str(has_xs))
    if not has_c_user or not has_xs:
        log("❌ Missing essential cookies (c_user or xs)")
        return False

    cookies = _normalize_cookies(cookies_raw)
    log("🍪 Loaded " + str(len(cookies)) + " cookies (of " + str(len(cookies_raw)) + " input)")

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
                page.goto(FB_HOME, wait_until="domcontentloaded", timeout=60000)
                time.sleep(5)
                url = page.url
                title = page.title()
                log("URL: " + url)
                log("Title: " + title)

                if "login" in url.lower() or "checkpoint" in url.lower():
                    log("❌ Cookies rejected — redirected to login/checkpoint")
                    try:
                        page.screenshot(
                            path="verify_acc" + str(acc_num) + "_fail.png",
                            full_page=True)
                        log("📸 Saved: verify_acc" + str(acc_num) + "_fail.png")
                    except Exception:
                        pass
                    return False

                cookies_now = page.context.cookies()
                log("📊 Cookies in context now: " + str(len(cookies_now)))
                c_user_now = next(
                    (c for c in cookies_now if c.get("name") == "c_user"),
                    None)
                if not c_user_now:
                    log("❌ c_user missing after navigation (session invalid)")
                    try:
                        page.screenshot(
                            path="verify_acc" + str(acc_num) + "_fail.png",
                            full_page=True)
                        log("📸 Saved: verify_acc" + str(acc_num) + "_fail.png")
                    except Exception:
                        pass
                    return False

                log("✅ Account #" + str(acc_num) + " verified! User ID: " + str(c_user_now.get("value")))
                return True
            except Exception as e:
                log("❌ Verification error: " + str(e))
                return False
        finally:
            browser.close()


def main():
    log("=" * 50)
    log("add_account.py v7.1 (cookies-only, mobile UA)")
    log("=" * 50)

    ok = []
    bad = []
    skip = []

    for i in range(1, 11):
        result = verify_account(i)
        if result is True:
            ok.append(i)
        elif result is False:
            bad.append(i)
        else:
            skip.append(i)

    log("=" * 50)
    log("Summary: ✅ OK=" + str(len(ok)) + " | ❌ Bad=" + str(len(bad)) + " | ⏭️  Skipped=" + str(len(skip)))
    if ok:
        log("  ✅ Valid accounts: " + str(ok))
    if bad:
        log("  ❌ Invalid accounts: " + str(bad))
    log("=" * 50)

    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
