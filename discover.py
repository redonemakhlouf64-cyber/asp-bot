#!/usr/bin/env python3
"""
discover.py v7.0 - Facebook Groups Discovery (Cookies-Only)
Searches FB Groups by keywords and saves URLs to groups.txt.
No email, no password, no proxy.
"""

import os
import json
import time
import random
import re
import sys
from urllib.parse import quote_plus
from playwright.sync_api import sync_playwright


def log(msg):
    print(f"[discover] {msg}", flush=True)


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
FB_COOKIES = os.environ.get(f"FB_COOKIES_{ACC_NUM}", "").strip()
KEYWORDS_RAW = os.environ.get("KEYWORDS", "").strip()
MAX_PER_KEYWORD = int(os.environ.get("MAX_PER_KEYWORD", "20"))

DEFAULT_KEYWORDS = [
    "business books",
    "finance books",
    "entrepreneurship books",
    "self improvement community",
    "digital books community",
    "YA readers USA",
    "fantasy readers USA",
    "design books",
    "value investing",
    "work from home USA",
]

DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0.0.0 Safari/537.36")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
window.chrome = {runtime: {}};
"""

GROUP_URL_RE = re.compile(r"facebook\.com/groups/([A-Za-z0-9._-]+)")


def get_keywords():
    if KEYWORDS_RAW:
        try:
            items = json.loads(KEYWORDS_RAW)
            if isinstance(items, list) and items:
                return [str(k).strip() for k in items if str(k).strip()]
        except Exception:
            pass
    return DEFAULT_KEYWORDS


def verify_login(page):
    log("STEP 1: Verify session with cookies")
    try:
        page.goto("https://www.facebook.com/",
                  wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        log(f"❌ goto failed: {e}")
        return False
    time.sleep(random.uniform(4, 6))

    url = page.url
    log(f"URL: {url}")

    if "login" in url.lower() or "checkpoint" in url.lower():
        log("❌ Redirected to login/checkpoint → cookies invalid")
        try:
            page.screenshot(path="discover_login_fail.png", full_page=True)
        except Exception:
            pass
        return False

    cookies_now = page.context.cookies()
    c_user = next((c for c in cookies_now if c.get("name") == "c_user"), None)
    if not c_user:
        log("❌ Missing c_user after navigation")
        try:
            page.screenshot(path="discover_no_cuser.png", full_page=True)
        except Exception:
            pass
        return False

    log(f"✅ Logged in as user id: {c_user.get('value')}")
    return True


def search_groups(page, keyword, max_results):
    """Search FB Groups tab for keyword. Returns list of group URLs."""
    log(f"🔍 '{keyword}'...")
    url = f"https://www.facebook.com/search/groups/?q={quote_plus(keyword)}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        log(f"  goto failed: {e}")
        return []

    # Give FB time to render results
    time.sleep(random.uniform(4, 6))

    # Scroll a bit to load more results
    for _ in range(3):
        try:
            page.mouse.wheel(0, 2000)
            time.sleep(random.uniform(1.5, 2.5))
        except Exception:
            break

    # Extract all group URLs from anchor tags
    urls = set()
    try:
        anchors = page.locator('a[href*="/groups/"]').all()
        for a in anchors:
            try:
                href = a.get_attribute("href") or ""
            except Exception:
                continue
            m = GROUP_URL_RE.search(href)
            if not m:
                continue
            slug = m.group(1)
            # Skip navigation/system links
            if slug in {"feed", "joins", "discover", "create", "invites"}:
                continue
            urls.add(f"https://www.facebook.com/groups/{slug}/")
            if len(urls) >= max_results:
                break
    except Exception as e:
        log(f"  extraction error: {e}")

    log(f"  → +{len(urls)} groups")
    return list(urls)


def main():
    log("=" * 50)
    log(f"discover.py v7.0 (cookies-only) | Acc #{ACC_NUM}")
    log("=" * 50)

    if not FB_COOKIES:
        log(f"❌ FB_COOKIES_{ACC_NUM} secret is empty")
        return 1

    try:
        cookies_raw = json.loads(FB_COOKIES)
    except Exception as e:
        log(f"❌ FB_COOKIES_{ACC_NUM} invalid JSON: {e}")
        return 1

    cookies = _normalize_cookies(cookies_raw)
    log(f"🍪 Loaded {len(cookies)} cookies")

    keywords = get_keywords()
    log(f"🔑 {len(keywords)} keywords to search")

    all_groups = set()
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
                log("❌ Cannot proceed — login failed")
                return 1

            for kw in keywords:
                found = search_groups(page, kw, MAX_PER_KEYWORD)
                all_groups.update(found)
                time.sleep(random.uniform(3, 6))
        finally:
            browser.close()

    log("=" * 50)
    log(f"✨ DONE — {len(all_groups)} unique groups found")
    log("=" * 50)

    # Save to groups.txt
    with open("groups.txt", "w", encoding="utf-8") as f:
        for u in sorted(all_groups):
            f.write(u + "\n")
    log(f"💾 Saved groups.txt with {len(all_groups)} URLs")

    return 0


if __name__ == "__main__":
    sys.exit(main())
