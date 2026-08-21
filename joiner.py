#!/usr/bin/env python3
"""
joiner.py v2.0 — بوت الانضمام التلقائي للجروبات
- يبحث بكلمات مفتاحية عبر 3 استراتيجيات
- ينضم للجروبات تلقائياً مع دفعات آمنة
- يحفظ التاريخ في joined_history.txt
"""

import os
import re
import sys
import time
import json
import random
import urllib.parse
from pathlib import Path
from playwright.sync_api import sync_playwright

# ============ الإعدادات ============
MBASIC = "https://mbasic.facebook.com"
ACCOUNT_NUM = int(os.environ.get("ACCOUNT_NUM", "1"))
FB_COOKIES = os.environ.get(f"FB_COOKIES_{ACCOUNT_NUM}", "")

# 🎯 نظام الدُفعات (Batch Mode)
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "30"))
BATCHES_PER_RUN = int(os.environ.get("BATCHES", "2"))
JOIN_DELAY_MIN = int(os.environ.get("JOIN_DELAY_MIN", "100"))
JOIN_DELAY_MAX = int(os.environ.get("JOIN_DELAY_MAX", "140"))
BATCH_PAUSE_MIN = int(os.environ.get("BATCH_PAUSE_MIN", "1800"))
BATCH_PAUSE_MAX = int(os.environ.get("BATCH_PAUSE_MAX", "2400"))

MAX_JOINS_PER_RUN = BATCH_SIZE * BATCHES_PER_RUN

# الملفات
KEYWORDS_FILE = "keywords.txt"
GROUPS_FILE = "groups.txt"
JOINED_FILE = "joined_history.txt"

USER_AGENT = "Mozilla/5.0 (Linux; Android 9; SM-G950F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36"


def log(msg):
    print(f"[joiner] {msg}", flush=True)


def load_cookies():
    if not FB_COOKIES:
        log(f"❌ FB_COOKIES_{ACCOUNT_NUM} empty")
        sys.exit(1)
    try:
        cookies = json.loads(FB_COOKIES)
        log(f"✅ Loaded {len(cookies)} cookies")
        return cookies
    except json.JSONDecodeError as e:
        log(f"❌ Invalid cookies JSON: {e}")
        sys.exit(1)


def load_keywords():
    if not Path(KEYWORDS_FILE).exists():
        log(f"❌ {KEYWORDS_FILE} not found")
        return []
    with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
        keywords = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    log(f"📚 Loaded {len(keywords)} keywords")
    return keywords


def load_existing_groups():
    existing = set()
    if Path(GROUPS_FILE).exists():
        with open(GROUPS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                match = re.search(r"/groups/(\d+)", line)
                if match:
                    existing.add(match.group(1))
                elif line.isdigit():
                    existing.add(line)
                else:
                    existing.add(line)
    log(f"📋 {len(existing)} groups already in {GROUPS_FILE}")
    return existing


def load_history():
    history = set()
    if Path(JOINED_FILE).exists():
        with open(JOINED_FILE, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("|")
                if parts:
                    history.add(parts[0].strip())
    log(f"📜 {len(history)} groups in history")
    return history


def save_joined_group(gid, result, keyword):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(JOINED_FILE, "a", encoding="utf-8") as f:
        f.write(f"{gid} | {result} | {keyword} | {timestamp}\n")
    if result in ("joined", "already"):
        with open(GROUPS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{gid}\n")


def search_groups_by_keyword(page, keyword, limit=10):
    """يبحث عن جروبات — v2 مع 3 استراتيجيات"""
    q = urllib.parse.quote(keyword)
    
    search_urls = [
        f"{MBASIC}/search/groups/?q={q}",
        f"{MBASIC}/search/top/?q={q}&filter=groups",
        f"{MBASIC}/groups/?category=membership&q={q}",
    ]
    
    group_ids = set()
    
    for search_url in search_urls:
        try:
            log(f"  🔍 Trying URL...")
            page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)
            
            html = page.content()
            
            # 1. IDs رقمية: /groups/123456789
            numeric_ids = re.findall(r"/groups/(\d{6,})", html)
            for gid in numeric_ids:
                group_ids.add(gid)
            
            # 2. Slugs نصية: /groups/some-name-here
            slug_matches = re.findall(r"/groups/([a-zA-Z][a-zA-Z0-9._-]{4,})[/?\"]", html)
            reserved = {"search", "browse", "discover", "feed", "join", "leave", "member", "create"}
            for slug in slug_matches:
                if slug.lower() not in reserved:
                    group_ids.add(slug)
            
            log(f"    → Found {len(group_ids)} candidates so far")
            
            if len(group_ids) >= limit:
                break
                
        except Exception as e:
            log(f"    ⚠️ URL failed: {e}")
            continue
    
    result = list(group_ids)[:limit]
    log(f"  ✅ Total for '{keyword}': {len(result)} groups")
    return result


def try_join_group(page, gid):
    """يحاول الانضمام — يرجع: joined / pending / already / failed"""
    try:
        url = f"{MBASIC}/groups/{gid}"
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(2)
        
        html_lower = page.content().lower()
        
        # هل أنا عضو بالفعل؟
        already_signals = ["leave group", "quitter le groupe", "مغادرة المجموعة", 
                           "posted in", "publier dans", "write something", "write a post"]
        if any(x in html_lower for x in already_signals):
            log(f"  ✓ Already member of {gid}")
            return "already"
        
        # ابحث عن زر الانضمام
        join_selectors = [
            "input[value='Join Group']",
            "input[value='Rejoindre le groupe']",
            "input[value='الانضمام إلى المجموعة']",
            "input[value*='Join']",
            "input[value*='Rejoindre']",
            "input[value*='انضم']",
            "a[href*='group_join']",
            "a[href*='groups/join']",
        ]
        
        clicked = False
        for sel in join_selectors:
            try:
                btn = page.query_selector(sel)
                if btn:
                    btn.click()
                    clicked = True
                    log(f"  👍 Clicked: {sel[:40]}")
                    break
            except Exception:
                continue
        
        if not clicked:
            # ربما أي رابط فيه join
            try:
                link = page.query_selector("a[href*='join']")
                if link:
                    link.click()
                    clicked = True
                    log(f"  👍 Clicked join link")
            except Exception:
                pass
        
        if not clicked:
            log(f"  ❌ No join button for {gid}")
            return "failed"
        
        # انتظر وتحقق من النتيجة
        time.sleep(3)
        html_lower = page.content().lower()
        
        pending_signals = ["pending", "en attente", "معلق", "cancel request", "annuler la demande"]
        if any(x in html_lower for x in pending_signals):
            log(f"  ⏳ Request pending for {gid}")
            return "pending"
        
        joined_signals = ["leave group", "quitter le groupe", "مغادرة", "joined"]
        if any(x in html_lower for x in joined_signals):
            log(f"  ✅ Joined {gid}")
            return "joined"
        
        # ربما يحتاج إجابة على أسئلة العضوية
        if "membership question" in html_lower or "questions d'adh" in html_lower:
            log(f"  ❓ Group {gid} requires membership questions")
            return "failed"
        
        log(f"  ❓ Unknown result for {gid}")
        return "pending"  # افتراضياً pending
        
    except Exception as e:
        log(f"  ⚠️ Error joining {gid}: {e}")
        return "failed"


def main():
    log("=" * 60)
    log("🤖 joiner.py v2.0 starting")
    log(f"Account: {ACCOUNT_NUM}")
    log(f"Plan: {BATCHES_PER_RUN} batches × {BATCH_SIZE} = {MAX_JOINS_PER_RUN} joins")
    log(f"Delay: {JOIN_DELAY_MIN}-{JOIN_DELAY_MAX}s | Pause: {BATCH_PAUSE_MIN//60}-{BATCH_PAUSE_MAX//60}min")
    log("=" * 60)
    
    cookies = load_cookies()
    keywords = load_keywords()
    if not keywords:
        log("❌ No keywords, exiting")
        sys.exit(1)
    
    existing = load_existing_groups()
    history = load_history()
    
    stats = {"joined": [], "pending": [], "skipped": [], "failed": []}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, viewport={"width": 412, "height": 915})
        context.add_cookies(cookies)
        page = context.new_page()
        
        try:
            # تحقق من صلاحية الكوكيز
            page.goto(f"{MBASIC}/", timeout=30000)
            time.sleep(2)
            if "login" in page.url or "checkpoint" in page.url:
                log("❌ Session invalid or checkpoint")
                sys.exit(1)
            log("✅ Session valid")
            
            joins_done = 0
            current_batch = 0
            batch_joins = 0
            random.shuffle(keywords)
            
            def flush_stop():
                return joins_done >= MAX_JOINS_PER_RUN
            
            for keyword in keywords:
                if flush_stop():
                    break
                
                log(f"\n🔎 Keyword: '{keyword}'")
                try:
                    candidates = search_groups_by_keyword(page, keyword, limit=10)
                except Exception as e:
                    log(f"⚠️ Search error: {e}")
                    continue
                
                for gid in candidates:
                    if flush_stop():
                        break
                    if gid in existing:
                        log(f"  ⏭️ {gid} already in groups.txt")
                        stats["skipped"].append(gid)
                        continue
                    if gid in history:
                        log(f"  ⏭️ {gid} tried before")
                        stats["skipped"].append(gid)
                        continue
                    
                    # إدارة الدُفعات
                    if batch_joins >= BATCH_SIZE:
                        current_batch += 1
                        if current_batch >= BATCHES_PER_RUN:
                            log(f"🛑 All {BATCHES_PER_RUN} batches done")
                            break
                        pause = random.randint(BATCH_PAUSE_MIN, BATCH_PAUSE_MAX)
                        log(f"\n☕ Batch {current_batch} done. Resting {pause//60} min...")
                        time.sleep(pause)
                        batch_joins = 0
                        log(f"🚀 Starting batch {current_batch + 1}/{BATCHES_PER_RUN}\n")
                    
                    delay = random.randint(JOIN_DELAY_MIN, JOIN_DELAY_MAX)
                    log(f"  ⏳ sleep {delay}s ({joins_done+1}/{MAX_JOINS_PER_RUN})")
                    time.sleep(delay)
                    
                    try:
                        result = try_join_group(page, gid)
                    except Exception as e:
                        log(f"  ⚠️ Join error: {e}")
                        result = "failed"
                    
                    save_joined_group(gid, result, keyword)
                    
                    if result == "joined":
                        stats["joined"].append(gid)
                        joins_done += 1
                        batch_joins += 1
                    elif result == "pending":
                        stats["pending"].append(gid)
                        joins_done += 1
                        batch_joins += 1
                    elif result == "already":
                        stats["skipped"].append(gid)
                    else:
                        stats["failed"].append(gid)
        
        finally:
            browser.close()
    
    log("\n" + "=" * 60)
    log("📊 النتائج النهائية")
    log("=" * 60)
    log(f"✅ Joined:  {len(stats['joined'])}")
    log(f"⏳ Pending: {len(stats['pending'])}")
    log(f"⏭️ Skipped: {len(stats['skipped'])}")
    log(f"❌ Failed:  {len(stats['failed'])}")
    log("=" * 60)


if __name__ == "__main__":
    main()
