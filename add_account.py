#!/usr/bin/env python3
"""
add_account.py v7.0 - Cookies-Only Verifier
No email, no password, no 2FA, no proxy.
Verifies FB_COOKIES_N secrets are valid and working.
"""

import os
import json
import time
import sys
from playwright.sync_api import sync_playwright


def log(msg):
    print(f"[add_account] {msg}", flush=True)


def _normalize_cookies(cookies):
    """Convert browser cookies (Firefox/Chrome) to Playwright format."""
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


DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0.0.0 Safari/537.36")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
window.chrome = {runtime: {}};
"""


def verify_account(acc_num):
    """Verify cookies for a single account. Returns True/False/None."""
    log(f"--- Verifying account #{acc_num} ---")
    fb_cookies = os.environ.get(f"FB_COOKIES_{acc_num}", "").strip()
    if not fb_cookies:
        log(f"⏭️  FB_COOKIES_{acc_num} not set. Skipping.")
        return None

    try:
        cookies_raw = json.loads(fb_cookies)
    except Exception as e:
        log(f"❌ FB_COOKIES_{acc_num} invalid JSON: {e}")
        return False

    has_c_user = any(c.get("name") == "c_user" for c in cookies_raw)
    has_xs = any(c.get("name") == "xs" for c in cookies_raw)
    log(f"🔍 c_user present: {has_c_user} | xs present: {has_xs}")
    if not has_c_user or not has_xs:
        log("❌ Missing essential cookies (c_user or xs)")
        return False

    cookies = _normalize_cookies(cookies_raw)
    log(f"🍪 Loaded {len(cookies)} cookies")

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

            try:
                page.goto("https://www.facebook.com/",
                          wait_until="domcontentloaded", timeout=60000)
                time.sleep(5)
                url = page.url
                log(f"URL: {url}")

                if "login" in url.lower() or "checkpoint" in url.lower():
                    log("❌ Cookies rejected — redirected to login/checkpoint")
                    try:
                        page.screenshot(
                            path=f"verify_acc{acc_num}_fail.png",
                            full_page=True)
                        log(f"📸 Saved: verify_acc{acc_num}_fail.png")
                    except Exception:
                        pass
                    return False

                cookies_now = page.context.cookies()
                c_user_now = next(
                    (c for c in cookies_now if c.get("name") == "c_user"),
                    None)
                if not c_user_now:
                    log("❌ c_user missing after navigation (session invalid)")
                    try:
                        page.screenshot(
                            path=f"verify_acc{acc_num}_fail.png",
                            full_page=True)
                        log(f"📸 Saved: verify_acc{acc_num}_fail.png")
                    except Exception:
                        pass
                    return False

                log(f"✅ Account #{acc_num} verified! User ID: {c_user_now.get('value')}")
                return True
            except Exception as e:
                log(f"❌ Verification error: {e}")
                return False
        finally:
            browser.close()


def main():
    log("=" * 50)
    log("add_account.py v7.0 (cookies-only verifier)")
    log("=" * 50)

    ok = []
    bad = []
    skip = []

    for i in range(1, 11):  # check up to 10 accounts
        result = verify_account(i)
        if result is True:
            ok.append(i)
        elif result is False:
            bad.append(i)
        else:
            skip.append(i)

    log("=" * 50)
    log(f"Summary: ✅ OK={len(ok)} | ❌ Bad={len(bad)} | ⏭️  Skipped={len(skip)}")
    if ok:
        log(f"  ✅ Valid accounts: {ok}")
    if bad:
        log(f"  ❌ Invalid accounts: {bad}")
    log("=" * 50)

    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
