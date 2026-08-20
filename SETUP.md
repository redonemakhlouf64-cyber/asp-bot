#!/usr/bin/env python3
"""Group Discovery - finds FB groups from keywords."""
import os, json, asyncio, random
from playwright.async_api import async_playwright

COOKIES_RAW = os.environ.get("FB_COOKIES", "").strip()
MAX_PER_KEYWORD = 5
MAX_TOTAL = 300

def log(m):
    print(f"[discover] {m}", flush=True)

def load_keywords():
    try:
        with open("keywords.txt") as f:
            return [l.strip() for l in f if l.strip() and not l.startswith("#")]
    except:
        return []

def load_existing():
    try:
        with open("groups.txt") as f:
            return set(l.strip() for l in f if l.strip().startswith("http"))
    except:
        return set()

def save_groups(groups):
    with open("groups.txt", "w") as f:
        for g in sorted(groups):
            f.write(g + "\n")

async def search_groups(page, keyword):
    found = []
    try:
        q = keyword.replace(" ", "%20")
        url = "https://www.facebook.com/search/groups/?q=" + q
        await page.goto(url, timeout=45000, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        for _ in range(3):
            await page.mouse.wheel(0, 3000)
            await page.wait_for_timeout(2000)
        links = await page.locator('a[href*="/groups/"]').all()
        seen = set()
        for l in links[:50]:
            try:
                href = await l.get_attribute("href")
                if href and "/groups/" in href:
                    parts = href.split("/groups/")[1].split("/")[0].split("?")[0]
                    if parts and parts not in seen and parts not in ("search", "feed", "discover"):
                        seen.add(parts)
                        found.append("https://www.facebook.com/groups/" + parts + "/")
                if len(found) >= MAX_PER_KEYWORD:
                    break
            except:
                continue
    except Exception as e:
        log(f"search fail '{keyword}': {str(e)[:60]}")
    return found

async def main():
    if not COOKIES_RAW:
        log("no cookies")
        return
    cookies = json.loads(COOKIES_RAW)
    keywords = load_keywords()
    random.shuffle(keywords)
    existing = load_existing()
    log(f"existing: {len(existing)}, keywords: {len(keywords)}")
    async with async_playwright() as p:
        br = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        try:
            ctx = await br.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768}
            )
            await ctx.add_cookies(cookies)
            page = await ctx.new_page()
            all_groups = set(existing)
            for kw in keywords[:60]:
                if len(all_groups) >= MAX_TOTAL:
                    break
                new = await search_groups(page, kw)
                before = len(all_groups)
                all_groups.update(new)
                added = len(all_groups) - before
                log(f"  '{kw}': +{added} (total {len(all_groups)})")
                await page.wait_for_timeout(random.randint(3000, 8000))
            save_groups(all_groups)
            log(f"DONE - {len(all_groups)} groups in groups.txt")
        finally:
            await br.close()

if __name__ == "__main__":
    asyncio.run(main())
