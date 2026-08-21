#!/usr/bin/env python3
"""
poster.py v8.0 — mbasic edition
يتجاوز مشكلة 'Utiliser l'application Facebook'
"""

import os
import sys
import json
import time
import random
from playwright.sync_api import sync_playwright

# ============ الإعدادات ============
ACCOUNT_NUM = int(os.environ.get("ACCOUNT_NUM", "1"))
CONTENT = os.environ.get("CONTENT", "").strip()
FB_COOKIES = os.environ.get(f"FB_COOKIES_{ACCOUNT_NUM}", "")
FORCE_ALL = os.environ.get("FORCE_ALL", "false").lower() == "true"
GROUP_IDS = [g.strip() for g in os.environ.get("GROUP_IDS", "").split(",") if g.strip()]

MBASIC = "https://mbasic.facebook.com"

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 9; SM-G950F) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/91.0.4472.120 Mobile Safari/537.36"
)


def log(msg):
    print(f"[poster] {msg}", flush=True)


def parse_cookies(cookie_str):
    cookies = []
    try:
        data = json.loads(cookie_str)
        if isinstance(data, list):
            for c in data:
                cookies.append({
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c.get("domain", ".facebook.com"),
                    "path": c.get("path", "/"),
                })
            return cookies
    except json.JSONDecodeError:
        pass

    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        cookies.append({
            "name": name.strip(),
            "value": value.strip(),
            "domain": ".facebook.com",
            "path": "/",
        })
    return cookies


def post_to_wall(page):
    log("📝 Posting to personal wall...")
    page.goto(f"{MBASIC}/composer/", timeout=30000, wait_until="domcontentloaded")
    page.screenshot(path="debug_wall_composer.png")

    textarea = (page.query_selector("textarea[name='xc_message']")
                or page.query_selector("textarea"))
    if not textarea:
        log("❌ No textarea in wall composer")
        return False

    textarea.fill(CONTENT)
    log(f"✅ Filled {len(CONTENT)} chars")

    submit = (page.query_selector("input[name='view_post']")
              or page.query_selector("input[type='submit']"))
    if not submit:
        log("❌ No submit button on wall")
        return False

    submit.click()
    page.wait_for_load_state("domcontentloaded", timeout=30000)

    confirm = (page.query_selector("input[value*='Confirmer']")
               or page.query_selector("input[value*='Confirm']"))
    if confirm:
        confirm.click()
        page.wait_for_load_state("domcontentloaded", timeout=30000)

    log("✅ Wall post done")
    return True


def post_to_group(page, group_id):
    log(f"👥 Posting to group {group_id}...")
    page.goto(f"{MBASIC}/groups/{group_id}", timeout=30000, wait_until="domcontentloaded")

    # اضغط على 'Write something'
    link = (page.query_selector("a:has-text('Write')")
            or page.query_selector("a:has-text('Écrire')")
            or page.query_selector("a:has-text('اكتب')"))
    if link:
        link.click()
        page.wait_for_load_state("domcontentloaded", timeout=30000)

    textarea = (page.query_selector("textarea[name='xc_message']")
                or page.query_selector("textarea"))
    if not textarea:
        log(f"❌ No textarea in group {group_id}")
        page.screenshot(path=f"debug_group_{group_id}_fail.png")
        return False

    textarea.fill(CONTENT)

    submit = (page.query_selector("input[name='view_post']")
              or page.query_selector("input[type='submit']"))
    if not submit:
        log(f"❌ No submit button in group {group_id}")
        return False

    submit.click()
    page.wait_for_load_state("domcontentloaded", timeout=30000)
    log(f"✅ Posted to group {group_id}")
    return True


def main():
    log("=" * 50)
    log("poster.py v8.0 (mbasic edition)")
    log(f"Account: #{ACCOUNT_NUM} | force_all={FORCE_ALL}")
    log(f"Groups: {len(GROUP_IDS)}")
    log("=" * 50)

    if not CONTENT:
        log("❌ CONTENT فارغ"); sys.exit(1)
    if not FB_COOKIES:
        log(f"❌ FB_COOKIES_{ACCOUNT_NUM} فارغ"); sys.exit(1)

    cookies = parse_cookies(FB_COOKIES)
    log(f"🍪 {len(cookies)} cookies loaded")
    log(f"📝 Preview: {CONTENT[:80]}...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 360, "height": 640},
            locale="en-US",
        )
        context.add_cookies(cookies)
        page = context.new_page()

        try:
            # STEP 1 — تحقّق من الجلسة
            log("STEP 1: verify session")
            page.goto(f"{MBASIC}/", timeout=30000, wait_until="domcontentloaded")
            if "login" in page.url or "checkpoint" in page.url:
                log(f"❌ Session invalid → {page.url}")
                page.screenshot(path="debug_session_fail.png")
                sys.exit(2)

            c_user = next((c["value"] for c in cookies if c["name"] == "c_user"), "?")
            log(f"✅ Logged in as {c_user}")

            # STEP 2 — انشر على الحائط
            post_to_wall(page)

            # STEP 3 — انشر في الجروبات
            for gid in GROUP_IDS:
                delay = random.randint(15, 40)
                log(f"⏳ Sleeping {delay}s before next group...")
                time.sleep(delay)
                try:
                    post_to_group(page, gid)
                except Exception as e:
                    log(f"⚠️ Group {gid} error: {e}")
                    continue

            log("🎉 Done.")

        except Exception as e:
            log(f"❌ Exception: {type(e).__name__}: {e}")
            try: page.screenshot(path="debug_exception.png")
            except: pass
            sys.exit(99)
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
