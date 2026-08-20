#!/usr/bin/env python3
"""Auto Poster v6.2 - Facebook groups + profile posting bot."""
import os, sys, json, time, random, asyncio, tempfile, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright

ACC = os.environ.get("ACCOUNT_NUM", "1").strip()
COOKIES_RAW = os.environ.get("FB_COOKIES", "").strip()
CONTENT_RAW = os.environ.get("CONTENT", "").strip()
IMAGES_RAW = os.environ.get("IMAGES", "").strip()
COMMENTS_RAW = os.environ.get("COMMENTS", "").strip()

WARMUP_DAYS = 3
LIGHT_DAYS = 3
WARMUP_STEP = 50
WARMUP_CAP = 500
COMMENT_PROBABILITY = 0.15
PROFILE_POST_PROBABILITY = 0.08
IMAGE_GROUP_RATE = 0.40
IMAGE_PROFILE_RATE = 0.30
MIN_DELAY = 45
MAX_DELAY = 100

WARMUP_POSTS = [
    "Good morning everyone!",
    "Feeling grateful today",
    "Coffee time",
    "Beautiful day outside",
    "Just finished a great book",
    "Learning something new every day",
    "Weekend vibes",
    "Motivation Monday",
    "Throwback to great memories",
    "Best decision I made this year",
    "Loving the weather today",
    "Family time is the best",
    "Working on myself",
    "Small progress is still progress",
    "Blessed and grateful",
    "New week, new goals",
    "Quiet morning thoughts",
    "Happy Friday everyone",
    "Just relaxing today",
    "Life is beautiful",
    "Chasing dreams",
    "Nothing beats a good sunset",
    "Making memories",
    "Positive vibes only",
    "Simple pleasures",
]

STATE_DIR = Path("state")
STATE_DIR.mkdir(exist_ok=True)
STATE_FILE = STATE_DIR / f"acc{ACC}.json"

def log(msg):
    print(f"[acc{ACC}] {msg}", flush=True)

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except:
            pass
    return {
        "first_run": datetime.now(timezone.utc).isoformat(),
        "day": 1,
        "warmup_posts": 0,
        "profile_posts": 0,
        "comments_made": 0,
        "groups_posted": [],
        "banned_groups": [],
        "posts_today": 0,
        "last_date": ""
    }

def save_state(s):
    STATE_FILE.write_text(json.dumps(s, indent=2))

def days_since(iso):
    try:
        first = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - first).days + 1
    except:
        return 1

def phase(state):
    d = days_since(state["first_run"])
    if d <= WARMUP_DAYS:
        return "warmup"
    if d <= WARMUP_DAYS + LIGHT_DAYS:
        return "light"
    return "full"

def cap_for_day(day):
    if day <= WARMUP_DAYS + LIGHT_DAYS:
        return 8
    over = day - (WARMUP_DAYS + LIGHT_DAYS)
    return min(WARMUP_CAP, WARMUP_STEP + over * WARMUP_STEP)

def load_content():
    per = os.environ.get(f"CONTENT_{ACC}", "").strip()
    raw = per if per else CONTENT_RAW
    lines = [l.strip() for l in raw.split("\n") if l.strip()]
    return lines if lines else ["Check this out!"]

def load_images():
    per = os.environ.get(f"IMAGES_{ACC}", "").strip()
    raw = per if per else IMAGES_RAW
    return [l.strip() for l in raw.split("\n") if l.strip().startswith("http")]

def load_comments():
    return [l.strip() for l in COMMENTS_RAW.split("\n") if l.strip()] or ["Great post!"]

def load_groups():
    try:
        with open("groups.txt", "r") as f:
            return [l.strip() for l in f if l.strip().startswith("http")]
    except:
        return []

def download_image(url):
    try:
        ext = ".jpg"
        for e in [".png", ".webp", ".gif", ".jpeg", ".jpg"]:
            if e in url.lower():
                ext = e
                break
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            tmp.write(r.read())
        tmp.close()
        return tmp.name
    except Exception as e:
        log(f"img download fail: {str(e)[:60]}")
        return None

async def human_delay(page, mn=MIN_DELAY, mx=MAX_DELAY):
    d = random.randint(mn, mx)
    await page.wait_for_timeout(d * 1000)

async def profile_post(page, text, image_path=None):
    try:
        await page.goto("https://www.facebook.com/", timeout=45000, wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)
        try:
            await page.locator('span:has-text("What\'s on your mind")').first.click(timeout=8000)
        except:
            await page.locator('div[role="button"]:has-text("What")').first.click(timeout=8000)
        await page.wait_for_timeout(3000)
        box = page.locator('div[contenteditable="true"][role="textbox"]').first
        await box.fill(text)
        await page.wait_for_timeout(2000)
        if image_path:
            try:
                await page.locator('input[type="file"]').first.set_input_files(image_path)
                await page.wait_for_timeout(6000)
            except Exception as e:
                log(f"img upload skip: {str(e)[:60]}")
        await page.wait_for_timeout(2000)
        try:
            await page.locator('div[aria-label="Post"][role="button"]').first.click(timeout=10000)
        except:
            await page.locator('div[role="button"]:has-text("Post")').first.click(timeout=10000)
        await page.wait_for_timeout(8000)
        return True
    except Exception as e:
        log(f"profile_post fail: {str(e)[:80]}")
        return False

async def group_post(page, group_url, text, image_path=None):
    try:
        await page.goto(group_url, timeout=45000, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        try:
            await page.locator('span:has-text("Write something")').first.click(timeout=8000)
        except:
            await page.locator('div[role="button"]:has-text("Write")').first.click(timeout=8000)
        await page.wait_for_timeout(3000)
        box = page.locator('div[contenteditable="true"][role="textbox"]').first
        await box.fill(text)
        await page.wait_for_timeout(2000)
        if image_path:
            try:
                await page.locator('input[type="file"]').first.set_input_files(image_path)
                await page.wait_for_timeout(6000)
            except:
                pass
        await page.wait_for_timeout(2000)
        try:
            await page.locator('div[aria-label="Post"][role="button"]').first.click(timeout=10000)
        except:
            await page.locator('div[role="button"]:has-text("Post")').first.click(timeout=10000)
        await page.wait_for_timeout(6000)
        return True
    except Exception as e:
        log(f"group_post fail: {str(e)[:80]}")
        return False

async def group_comment(page, group_url, comment):
    try:
        await page.goto(group_url, timeout=45000, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        try:
            await page.locator('div[aria-label="Leave a comment"]').first.click(timeout=8000)
        except:
            await page.locator('span:has-text("Comment")').first.click(timeout=8000)
        await page.wait_for_timeout(3000)
        box = page.locator('div[contenteditable="true"][aria-label*="omment"]').first
        await box.fill(comment)
        await page.wait_for_timeout(2000)
        await box.press("Enter")
        await page.wait_for_timeout(5000)
        return True
    except Exception as e:
        log(f"comment fail: {str(e)[:80]}")
        return False

async def run_warmup(page, state):
    n = random.randint(1, 2)
    log(f"WARMUP: {n} profile posts")
    for i in range(n):
        text = random.choice(WARMUP_POSTS)
        ok = await profile_post(page, text)
        if ok:
            state["warmup_posts"] += 1
            state["profile_posts"] += 1
            log(f"  warmup post {i+1}/{n} OK")
        save_state(state)
        if i < n - 1:
            await human_delay(page, 120, 300)

async def run_groups(page, state, is_light=False):
    contents = load_content()
    images = load_images()
    comments = load_comments()
    groups = load_groups()
    if not groups:
        log("no groups.txt yet - waiting for discovery")
        return
    banned = set(state.get("banned_groups", []))
    avail = [g for g in groups if g not in banned]
    random.shuffle(avail)
    day = days_since(state["first_run"])
    daily_cap = 8 if is_light else cap_for_day(day)
    max_ops = min(daily_cap, len(avail))
    if is_light:
        max_ops = random.randint(3, 8)
    log(f"GROUPS: day {day}, cap {daily_cap}, planned {max_ops} ops on {len(avail)} groups")
    done = 0
    for g in avail[:max_ops]:
        if random.random() < COMMENT_PROBABILITY and not is_light:
            c = random.choice(comments)
            ok = await group_comment(page, g, c)
            if ok:
                state["comments_made"] += 1
                log(f"  comment [{done+1}/{max_ops}] OK")
            else:
                banned.add(g)
                state["banned_groups"] = list(banned)
        else:
            text = random.choice(contents)
            img = None
            if images and random.random() < IMAGE_GROUP_RATE:
                img = download_image(random.choice(images))
            ok = await group_post(page, g, text, img)
            if img:
                try:
                    os.unlink(img)
                except:
                    pass
            if ok:
                state["groups_posted"].append(g)
                state["posts_today"] += 1
                log(f"  post [{done+1}/{max_ops}] OK")
            else:
                banned.add(g)
                state["banned_groups"] = list(banned)
        save_state(state)
        done += 1
        await human_delay(page)
    if random.random() < PROFILE_POST_PROBABILITY and not is_light:
        log("BONUS: profile filler post")
        text = random.choice(load_content())
        img = None
        if images and random.random() < IMAGE_PROFILE_RATE:
            img = download_image(random.choice(images))
        ok = await profile_post(page, text, img)
        if img:
            try:
                os.unlink(img)
            except:
                pass
        if ok:
            state["profile_posts"] += 1
        save_state(state)

async def main():
    if not COOKIES_RAW:
        log("no cookies - skip")
        return
    try:
        cookies = json.loads(COOKIES_RAW)
    except:
        log("bad cookies JSON - skip")
        return
    state = load_state()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state.get("last_date") != today:
        state["posts_today"] = 0
        state["last_date"] = today
        state["day"] = days_since(state["first_run"])
    ph = phase(state)
    log(f"phase={ph} day={days_since(state['first_run'])}")
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
            await page.goto("https://www.facebook.com/", timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)
            if "login" in page.url:
                log("session expired - need re-login")
                return
            log("session OK")
            if ph == "warmup":
                await run_warmup(page, state)
            elif ph == "light":
                await run_groups(page, state, is_light=True)
            else:
                await run_groups(page, state, is_light=False)
            save_state(state)
            log(f"DONE - posts_today={state['posts_today']}, total_groups={len(state['groups_posted'])}")
        finally:
            await br.close()

if __name__ == "__main__":
    asyncio.run(main())
