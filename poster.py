#!/usr/bin/env python3
"""
poster.py - Facebook Auto Poster v6.6
Uses saved cookies to post to Facebook without login.
"""

import os
import json
import time
import random
import sys
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright


def log(msg):
    print(f"[poster] {msg}", flush=True)


def _normalize_cookies(cookies):
    """Convert browser cookies (Firefox/Chrome) to Playwright format."""
    ss_map = {
        "lax": "Lax",
        "strict": "Strict",
        "none": "None",
        "no_restriction": "None",
    }
    allowed = {"name", "value", "domain", "path", "expires",
               "httpOnly", "secure", "sameSite"}
    out = []
    for c in cookies:
        nc = {}
        for k, v in c.items():
            if k == "expirationDate":
                nc["expires"] = float(v) if v is not None else -1
            elif k == "sameSite":
                if v is None or v == "":
                    nc["sameSite"] = "Lax"
                else:
                    nc["sameSite"] = ss_map.get(str(v).lower(), "Lax")
            elif k in allowed:
                nc[k] = v
        if "sameSite" not in nc:
            nc["sameSite"] = "Lax"
        if "domain" not in nc:
            continue
        if "path" not in nc:
            nc["path"] = "/"
        out.append(nc)
    return out


def parse_proxy(url):
    """Parse PROXY_URL into Playwright proxy config."""
    if not url:
        return None
    p = urlparse(url)
    cfg = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
    if p.username:
        cfg["username"] = p.username
    if p.password:
        cfg["password"] = p.password
    return cfg


ACC_NUM = int(os.environ.get("ACCOUNT_NUM", "1"))
FORCE_ALL = os.environ.get("FORCE_ALL", "false").lower() == "true"
PROXY_URL = os.environ.get("PROXY_URL", "").strip()
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


def post_to_profile(page):
    log("Navigating to FB home...")
    page.goto("https://www.facebook.com/",
              wait_until="domcontentloaded", timeout=60000)
    time.sleep(random.uniform(4, 7))

    current_url = page.url
    log(f"Current URL: {current_url}")
    if "login" in current_url or "checkpoint" in current_url:
        log("NOT logged in - cookies invalid or expired")
        return False

    log("Opening compose box...")
    compose_selectors = [
        'span:has-text("What\'s on your mind")',
        'div[role="button"]:has-text("What\'s on your mind")',
        '[aria-label*="Create a post"]',
    ]
    opened = False
    for sel in compose_selectors:
        try:
            page.locator(sel).first.click(timeout=8000)
            opened = True
            log(f"Compose opened with: {sel}")
            break
        except Exception:
            continue
    if not opened:
        log("Could not open compose box")
        return False

    time.sleep(random.uniform(2, 4))

    text = get_content()
    log(f"Content: {text[:100]}")
    try:
        editor = page.locator(
            'div[contenteditable="true"][role="textbox"]').first
        editor.click(timeout=10000)
        time.sleep(1)
        editor.type(text, delay=random.randint(30, 80))
    except Exception as e:
        log(f"Type failed: {e}")
        return False

    time.sleep(random.uniform(3, 5))

    log("Clicking Post button...")
    post_selectors = [
        'div[aria-label="Post"][role="button"]',
        'div[aria-label="Post"]',
        'button:has-text("Post")',
    ]
    posted = False
    for sel in post_selectors:
        try:
            page.locator(sel).first.click(timeout=8000)
            posted = True
            log(f"Post clicked with: {sel}")
            break
        except Exception:
            continue
    if not posted:
        log("Could not click Post button")
        return False

    log("Waiting for post to submit...")
    time.sleep(random.uniform(6, 10))
    log("Post submitted successfully")
    return True


def main():
    log("=== poster.py v6.6 START ===")
    log(f"Account: #{ACC_NUM}, Force: {FORCE_ALL}")

    if not FB_COOKIES:
        log(f"No FB_COOKIES_{ACC_NUM} secret found. Skipping.")
        return 0

    try:
        cookies_raw = json.loads(FB_COOKIES)
    except Exception as e:
        log(f"FB_COOKIES_{ACC_NUM} invalid JSON: {e}")
        return 1

    cookies = _normalize_cookies(cookies_raw)
    log(f"Loaded {len(cookies)} cookies (normalized)")

    proxy_cfg = parse_proxy(PROXY_URL)
    if proxy_cfg:
        log(f"Using proxy: {proxy_cfg['server']}")
    else:
        log("WARNING: No proxy configured")

    success = False
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        try:
            ctx_args = {
                "user_agent": DESKTOP_UA,
                "viewport": {"width": 1366, "height": 768},
                "locale": "en-US",
            }
            if proxy_cfg:
                ctx_args["proxy"] = proxy_cfg
            context = browser.new_context(**ctx_args)
            context.add_init_script(STEALTH_JS)
            context.add_cookies(cookies)
            page = context.new_page()

            try:
                success = post_to_profile(page)
            except Exception as e:
                log(f"Post error: {e}")
                success = False

            if not success:
                try:
                    page.screenshot(
                        path=f"failure_acc{ACC_NUM}.png", full_page=True)
                    log(f"Screenshot saved: failure_acc{ACC_NUM}.png")
                except Exception:
                    pass
        finally:
            browser.close()

    log(f"=== poster.py v6.6 END - {'OK' if success else 'FAIL'} ===")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
