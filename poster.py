#!/usr/bin/env python3
"""
poster.py v8.4 — mbasic edition (asp-bot final)
- يقرأ groups.txt (يدعم URL أو ID)
- ينشر على الحائط وفي الجروبات
- يحذف الجروبات الفاشلة تلقائياً
"""

import os
import re
import sys
import json
import time
import random
from pathlib import Path
from collections import Counter
from playwright.sync_api import sync_playwright

# ============ الإعدادات ============
ACCOUNT_NUM = int(os.environ.get("ACCOUNT_NUM", "1"))
CONTENT = os.environ.get("CONTENT", "").strip()
FB_COOKIES = os.environ.get(f"FB_COOKIES_{ACCOUNT_NUM}", "")
FORCE_ALL = os.environ.get("FORCE_ALL", "false").lower() == "true"
AUTO_REMOVE_FAILED = os.environ.get("AUTO_REMOVE_FAILED", "true").lower() == "true"

MBASIC = "https://mbasic.facebook.com"
GROUPS_FILE = Path("groups.txt")
FAILED_FILE = Path("failed_groups.txt")

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 9; SM-G950F) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/91.0.4472.120 Mobile Safari/537.36"
)

stats = {"ok": [], "failed": [], "reasons": {}}


def log(msg):
    print(f"[poster] {msg}", flush=True)


def extract_group_id(line):
    line = line.strip().rstrip("/")
    if line.isdigit():
        return line
    m = re.search(r"/groups/(\d+)", line)
    if m:
        return m.group(1)
    m = re.search(r"/groups/([^/?&#]+)", line)
    if m:
        return m.group(1)
    return line


def load_groups():
    if not GROUPS_FILE.exists():
        return []
    ids = []
    for ln in GROUPS_FILE.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        gid = extract_group_id(s)
        if gid:
            ids.append(gid)
    return ids


def remove_failed_from_groups(failed_ids):
    if not failed_ids or not GROUPS_FILE.exists():
        return
    lines = GROUPS_FILE.read_text(encoding="utf-8").splitlines()
    kept, removed = [], []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#"):
            kept.append(ln)
            continue
        gid = extract_group_id(s)
        if gid in failed_ids:
            removed.append(ln)
        else:
            kept.append(ln)
    if removed:
        GROUPS_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")
        with FAILED_FILE.open("a", encoding="utf-8") as f:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            for ln in removed:
                gid = extract_group_id(ln.strip())
                reason = stats["reasons"].get(gid, "unknown")
                f.write(f"{ts} | {reason} | {ln.strip()}\n")
        log(f"🗑️ Removed {len(removed)} groups → saved to failed_groups.txt")


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


def find_textarea(page):
    for sel in [
        "textarea[name='xc_message']",
        "textarea[name='status']",
        "textarea[placeholder*='penses']",
        "textarea[placeholder*='thinking']",
        "textarea[placeholder*='تفكر']",
        "textarea",
    ]:
        el = page.query_selector(sel)
        if el:
            return el
    return None


def detect_failure_reason(page):
    url = page.url.lower()
    if "checkpoint" in url:
        return "checkpoint"
    if "login" in url:
        return "session_expired"
    if "www.facebook.com" in url and "mbasic" not in url:
        return "redirect_www"
    c = page.content().lower()
    if "you must be a member" in c or "vous devez être membre" in c or "يجب أن تكون عضواً" in c:
        return "not_member"
    if "this group is closed" in c or "groupe fermé" in c:
        return "group_closed"
    if "content not found" in c or "introuvable" in c or "unavailable" in c:
        return "not_found"
    return "no_textarea"


def is_session_alive(page):
    url = page.url.lower()
    return "login" not in url and "checkpoint" not in url


def post_to_wall(page):
    log("📝 Wall...")
    for url in [f"{MBASIC}/home.php", f"{MBASIC}/", f"{MBASIC}/composer/"]:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        ta = find_textarea(page)
        if ta:
            log(f"  ✅ textarea @ {url}")
            break
        link = (page.query_selector("a[href*='composer']")
                or page.query_selector("a:has-text('penses')")
                or page.query_selector("a:has-text('mind')"))
        if link:
            link.click()
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            ta = find_textarea(page)
            if ta:
                break
    else:
        ta = None
    if not ta:
        log("❌ wall failed")
        return False
    ta.fill(CONTENT)
    submit = (page.query_selector("input[name='view_post']")
              or page.query_selector("input[type='submit']"))
    if not submit:
        return False
    submit.click()
    page.wait_for_load_state("domcontentloaded", timeout=30000)
    confirm = (page.query_selector("input[value*='Confirmer']")
               or page.query_selector("input[value*='Confirm']"))
    if confirm:
        confirm.click()
        page.wait_for_load_state("domcontentloaded", timeout=30000)
    log("✅ wall done")
    return True


def post_to_group(page, gid):
    log(f"👥 {gid}...")
    urls = [
        f"{MBASIC}/composer/?target_id={gid}",
        f"{MBASIC}/groups/{gid}?view=permalink",
        f"{MBASIC}/groups/{gid}",
    ]
    ta = None
    for url in urls:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        if not is_session_alive(page):
            return False, "session_expired"
        ta = find_textarea(page)
        if ta:
            break
        link = (page.query_selector("a[href*='composer'][href*='target_id']")
                or page.query_selector("a:has-text('Write')")
                or page.query_selector("a:has-text('Écrire')")
                or page.query_selector("a:has-text('اكتب')"))
        if link:
            link.click()
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            ta = find_textarea(page)
            if ta:
                break
    if not ta:
        reason = detect_failure_reason(page)
        log(f"  ❌ {reason}")
        return False, reason
    ta.fill(CONTENT)
    submit = (page.query_selector("input[name='view_post']")
              or page.query_selector("input[type='submit']"))
    if not submit:
        return False, "no_submit"
    submit.click()
    page.wait_for_load_state("domcontentloaded", timeout=30000)
    log(f"  ✅ posted")
    return True, "ok"


def main():
    log("=" * 50)
    log("poster.py v8.4 (final)")
    log(f"Account #{ACCOUNT_NUM} | auto_remove={AUTO_REMOVE_FAILED}")
    log("=" * 50)

    if not CONTENT:
        log("❌ CONTENT empty"); sys.exit(1)
    if not FB_COOKIES:
        log(f"❌ FB_COOKIES_{ACCOUNT_NUM} empty"); sys.exit(1)

    gids = load_groups()
    log(f"📂 Groups: {len(gids)}")
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
            page.goto(f"{MBASIC}/", timeout=30000, wait_until="domcontentloaded")
            if not is_session_alive(page):
                log(f"❌ Session invalid → {page.url}")
                sys.exit(2)
            cu = next((c["value"] for c in cookies if c["name"] == "c_user"), "?")
            log(f"✅ Logged in as {cu}")

            post_to_wall(page)

            for gid in gids:
                d = random.randint(15, 40)
                log(f"⏳ sleep {d}s")
                time.sleep(d)
                try:
                    ok, reason = post_to_group(page, gid)
                    if ok:
                        stats["ok"].append(gid)
                    else:
                        stats["failed"].append(gid)
                        stats["reasons"][gid] = reason
                        if reason in ("session_expired", "checkpoint"):
                            log("🛑 Session broken — stop")
                            break
                except Exception as e:
                    log(f"⚠️ {gid}: {type(e).__name__}: {e}")
                    stats["failed"].append(gid)
                    stats["reasons"][gid] = "exception"

            log("=" * 50)
            log(f"✅ Success: {len(stats['ok'])}")
            log(f"❌ Failed:  {len(stats['failed'])}")
            for r, n in Counter(stats["reasons"].values()).items():
                log(f"   • {r}: {n}")

            if AUTO_REMOVE_FAILED and stats["failed"]:
                temp = {"session_expired", "checkpoint", "exception"}
                to_del = [g for g in stats["failed"]
                          if stats["reasons"].get(g) not in temp]
                if to_del:
                    remove_failed_from_groups(to_del)
                else:
                    log("ℹ️ Temporary failures only — groups.txt kept")

            log("🎉 Done.")

        except Exception as e:
            log(f"❌ Fatal: {type(e).__name__}: {e}")
            sys.exit(99)
        finally:
            ctx.close()
            browser.close()


if __name__ == "__main__":
    main()
