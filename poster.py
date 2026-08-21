#!/usr/bin/env python3
"""
poster.py v8.2 — mbasic edition (asp-bot compatible)
- يقرأ groups.txt من جذر المستودع
- يستخدم composer/?target_id لتجنّب إعادة توجيه الجروبات
- يكتشف إعادة التوجيه إلى www ويعالجه
- selectors احتياطية متعددة
"""

import os
import sys
import json
import time
import random
from pathlib import Path
from playwright.sync_api import sync_playwright

# ============ الإعدادات ============
ACCOUNT_NUM = int(os.environ.get("ACCOUNT_NUM", "1"))
CONTENT = os.environ.get("CONTENT", "").strip()
FB_COOKIES = os.environ.get(f"FB_COOKIES_{ACCOUNT_NUM}", "")
FORCE_ALL = os.environ.get("FORCE_ALL", "false").lower() == "true"

# قراءة الجروبات من groups.txt (سطر لكل ID)
def load_groups():
    p = Path("groups.txt")
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]

GROUP_IDS = load_groups()

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


def find_composer_textarea(page):
    """يجرّب عدة selectors لإيجاد textarea التأليف."""
    selectors = [
        "textarea[name='xc_message']",
        "textarea[name='status']",
        "textarea[placeholder*='penses']",   # FR: À quoi penses-tu?
        "textarea[placeholder*='thinking']", # EN
        "textarea[placeholder*='تفكر']",     # AR
        "textarea",
    ]
    for sel in selectors:
        el = page.query_selector(sel)
        if el:
            log(f"  ↳ textarea found via: {sel}")
            return el
    return None


def post_to_wall(page):
    log("📝 Posting to personal wall...")
    # جرّب 3 URLs مختلفة للحائط
    urls_to_try = [
        f"{MBASIC}/home.php",
        f"{MBASIC}/",
        f"{MBASIC}/composer/",
    ]
    textarea = None
    for url in urls_to_try:
        log(f"  → Trying {url}")
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        page.screenshot(path=f"debug_wall_{url.rsplit('/',1)[-1] or 'home'}.png")
        textarea = find_composer_textarea(page)
        if textarea:
            log(f"  ✅ textarea available at {url}")
            break
        # ابحث عن رابط "What's on your mind" واضغطه
        link = (page.query_selector("a[href*='composer']")
                or page.query_selector("a:has-text('penses')")
                or page.query_selector("a:has-text('mind')"))
        if link:
            log("  → Clicking composer link...")
            link.click()
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            textarea = find_composer_textarea(page)
            if textarea:
                break

    if not textarea:
        log("❌ No textarea in wall composer (tried all URLs)")
        # اطبع HTML للتشخيص
        html_preview = page.content()[:3000]
        log(f"HTML preview:\n{html_preview}")
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

    # جرّب 3 URLs مختلفة لتجنّب إعادة التوجيه إلى www
    urls_to_try = [
        f"{MBASIC}/composer/?target_id={group_id}",   # ⭐ أفضل طريقة
        f"{MBASIC}/groups/{group_id}?view=permalink",
        f"{MBASIC}/groups/{group_id}",
    ]

    textarea = None
    for url in urls_to_try:
        log(f"  → Trying {url}")
        page.goto(url, timeout=30000, wait_until="domcontentloaded")

        # تحقّق إذا تمّ إعادة التوجيه
        current = page.url
        if "www.facebook.com" in current or "m.facebook.com" in current and "mbasic" not in current:
            log(f"  ⚠️ Redirected to {current} — forcing back to mbasic")
            # أعد المحاولة مع header يجبر mbasic
            page.set_extra_http_headers({"X-Requested-With": "XMLHttpRequest"})
            page.goto(url, timeout=30000, wait_until="domcontentloaded")

        textarea = find_composer_textarea(page)
        if textarea:
            log(f"  ✅ textarea found at {url}")
            break

        # جرّب الضغط على 'Write something'
        link = (page.query_selector("a[href*='composer'][href*='target_id']")
                or page.query_selector("a:has-text('Write')")
                or page.query_selector("a:has-text('Écrire')")
                or page.query_selector("a:has-text('اكتب')"))
        if link:
            log("  → Clicking composer link...")
            link.click()
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            textarea = find_composer_textarea(page)
            if textarea:
                break

    if not textarea:
        log(f"❌ No textarea in group {group_id}")
        page.screenshot(path=f"debug_group_{group_id}_fail.png")
        # اطبع HTML للتشخيص (لأول جروب فقط لتجنّب إغراق اللوج)
        log(f"Final URL: {page.url}")
        log(f"HTML preview (first 2000 chars):\n{page.content()[:2000]}")
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
