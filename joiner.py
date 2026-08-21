#!/usr/bin/env python3
"""
joiner.py v1.0 — بوت الانضمام التلقائي للجروبات
- يبحث عن جروبات بالكلمات المفتاحية
- ينضم لكل جروب (يضغط زر Join)
- يحفظ الجروبات المنضم إليها في groups.txt
"""

import os
import re
import sys
import json
import time
import random
from pathlib import Path
from playwright.sync_api import sync_playwright

# ============ الإعدادات ============
ACCOUNT_NUM = int(os.environ.get("ACCOUNT_NUM", "1"))
FB_COOKIES = os.environ.get(f"FB_COOKIES_{ACCOUNT_NUM}", "")
MAX_JOINS_PER_RUN = int(os.environ.get("MAX_JOINS", "5"))  # حد آمن

MBASIC = "https://mbasic.facebook.com"
KEYWORDS_FILE = Path("keywords.txt")
GROUPS_FILE = Path("groups.txt")
JOINED_FILE = Path("joined_history.txt")

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 9; SM-G950F) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/91.0.4472.120 Mobile Safari/537.36"
)

stats = {"joined": [], "pending": [], "failed": [], "skipped": []}


def log(msg):
    print(f"[joiner] {msg}", flush=True)


def load_keywords():
    if not KEYWORDS_FILE.exists():
        return []
    return [k.strip() for k in KEYWORDS_FILE.read_text(encoding="utf-8").splitlines()
            if k.strip() and not k.startswith("#")]


def load_existing_groups():
    """يحمل الجروبات الحالية لتجنب التكرار"""
    if not GROUPS_FILE.exists():
        return set()
    ids = set()
    for ln in GROUPS_FILE.read_text(encoding="utf-8").splitlines():
        m = re.search(r"/groups/(\d+)", ln)
        if m:
            ids.add(m.group(1))
        elif ln.strip().isdigit():
            ids.add(ln.strip())
    return ids


def load_history():
    """يحمل تاريخ الجروبات المحاولة مسبقاً"""
    if not JOINED_FILE.exists():
        return set()
    ids = set()
    for ln in JOINED_FILE.read_text(encoding="utf-8").splitlines():
        parts = ln.split("|")
        if len(parts) >= 2:
            ids.add(parts[1].strip())
    return ids


def parse_cookies(cookie_str):
    cookies = []
    try:
        data = json.loads(cookie_str)
        if isinstance(data, list):
            for c in data:
                cookies.append({
                    "name": c["name"], "value": c["value"],
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
            "name": name.strip(), "value": value.strip(),
            "domain": ".facebook.com", "path": "/",
        })
    return cookies


def search_groups_by_keyword(page, keyword, limit=10):
    """يبحث في فيسبوك عن جروبات تحتوي الكلمة"""
    log(f"🔍 Searching: '{keyword}'")
    search_url = f"{MBASIC}/search/groups/?q={keyword}"
    page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
    time.sleep(2)

    group_ids = []
    links = page.query_selector_all("a[href*='/groups/']")
    seen = set()
    for link in links:
        href = link.get_attribute("href") or ""
        m = re.search(r"/groups/(\d+)", href)
        if m:
            gid = m.group(1)
            if gid not in seen:
                seen.add(gid)
                group_ids.append(gid)
                if len(group_ids) >= limit:
                    break

    log(f"  → Found {len(group_ids)} groups")
    return group_ids


def try_join_group(page, gid):
    """يحاول الانضمام لجروب. يرجع: 'joined' / 'pending' / 'already' / 'failed'"""
    log(f"🚪 Joining {gid}...")
    url = f"{MBASIC}/groups/{gid}"
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    time.sleep(1)

    content_lower = page.content().lower()

    # عضو مسبقاً؟
    if "leave group" in content_lower or "quitter le groupe" in content_lower:
        log("  ℹ️ Already a member")
        return "already"

    # ابحث عن زر الانضمام (بعدة لغات)
    join_selectors = [
        "input[value='Join Group']",
        "input[value='Rejoindre le groupe']",
        "input[value='الانضمام إلى المجموعة']",
        "a:has-text('Join Group')",
        "a:has-text('Rejoindre')",
        "a:has-text('انضم')",
        "a[href*='group_join']",
        "a[href*='join']",
    ]

    join_btn = None
    for sel in join_selectors:
        try:
            btn = page.query_selector(sel)
            if btn:
                join_btn = btn
                break
        except Exception:
            continue

    if not join_btn:
        log("  ❌ No join button")
        return "failed"

    try:
        join_btn.click()
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        time.sleep(2)
    except Exception as e:
        log(f"  ⚠️ Click error: {e}")
        return "failed"

    # هل هناك سؤال قبول؟
    if page.query_selector("textarea[name*='answer']") or \
       "membership question" in page.content().lower():
        log("  ⏸️ Has membership questions — skip")
        return "failed"

    # هل تم قبوله؟
    new_content = page.content().lower()
    if "leave group" in new_content or "quitter" in new_content:
        log("  ✅ Joined immediately")
        return "joined"
    if "pending" in new_content or "en attente" in new_content or "awaiting" in new_content:
        log("  ⏳ Pending admin approval")
        return "pending"

    log("  ✅ Request sent")
    return "pending"


def save_joined_group(gid, status, keyword):
    """يضيف الجروب لـ groups.txt (فقط المقبولة) + التاريخ"""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")

    with JOINED_FILE.open("a", encoding="utf-8") as f:
        f.write(f"{ts} | {gid} | {status} | {keyword}\n")

    # فقط المقبولة تُضاف لـ groups.txt للنشر
    if status == "joined":
        with GROUPS_FILE.open("a", encoding="utf-8") as f:
            f.write(f"https://www.facebook.com/groups/{gid}/\n")


def main():
    log("=" * 50)
    log("joiner.py v1.0")
    log(f"Account #{ACCOUNT_NUM} | max_joins={MAX_JOINS_PER_RUN}")
    log("=" * 50)

    if not FB_COOKIES:
        log(f"❌ FB_COOKIES_{ACCOUNT_NUM} empty"); sys.exit(1)

    keywords = load_keywords()
    if not keywords:
        log("❌ keywords.txt empty"); sys.exit(1)
    log(f"📝 Keywords: {len(keywords)}")

    existing = load_existing_groups()
    history = load_history()
    log(f"📂 Existing groups: {len(existing)} | History: {len(history)}")

    cookies = parse_cookies(FB_COOKIES)
    log(f"🍪 Cookies: {len(cookies)}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 360, "height": 640},
            locale="en-US",
        )
        ctx.add_cookies(cookies)
        page = ctx.new_page()

        try:
            # تحقق الجلسة
            page.goto(f"{MBASIC}/", timeout=30000)
            if "login" in page.url or "checkpoint" in page.url:
                log(f"❌ Session invalid → {page.url}"); sys.exit(2)
            log("✅ Session valid")

            joins_done = 0
            random.shuffle(keywords)

            for keyword in keywords:
                if joins_done >= MAX_JOINS_PER_RUN:
                    log(f"🛑 Reached max joins ({MAX_JOINS_PER_RUN})")
                    break

                try:
                    candidates = search_groups_by_keyword(page, keyword, limit=5)
                except Exception as e:
                    log(f"⚠️ Search error: {e}")
                    continue

                for gid in candidates:
                    if joins_done >= MAX_JOINS_PER_RUN:
                        break
                    if gid in existing:
                        log(f"  ⏭️ {gid} already in groups.txt")
                        stats["skipped"].append(gid)
                        continue
                    if gid in history:
                        log(f"  ⏭️ {gid} tried before")
                        stats["skipped"].append(gid)
                        continue

                    # انتظار عشوائي (30-90 ثانية بين محاولات الانضمام)
                    delay = random.randint(30, 90)
                    log(f"⏳ sleep {delay}s")
                    time.sleep(delay)

                    try:
                        result = try_join_group(page, gid)
                    except Exception as e:
                        log(f"⚠️ Join error: {e}")
                        result = "failed"

                    save_joined_group(gid, result, keyword)

                    if result == "joined":
                        stats["joined"].append(gid)
                        joins_done += 1
                    elif result == "pending":
                        stats["pending"].append(gid)
                        joins_done += 1
                    elif result == "already":
                        stats["skipped"].append(gid)
                    else:
                        stats["failed"].append(gid)

            # النتيجة النهائية
            log("=" * 50)
            log(f"✅ Joined:  {len(stats['joined'])}")
            log(f"⏳ Pending: {len(stats['pending'])}")
            log(f"⏭️ Skipped: {len(stats['skipped'])}")
            log(f"❌ Failed:  {len(stats['failed'])}")
            log("🎉 Done.")

        except Exception as e:
            log(f"❌ Fatal: {type(e).__name__}: {e}")
            sys.exit(99)
        finally:
            ctx.close()
            browser.close()


if __name__ == "__main__":
    main()
