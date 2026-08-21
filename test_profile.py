"""
test_profile.py — Warmup bot + posting test.
1. Login via cookies
2. Anti-detection Chrome setup
3. WARMUP: scroll, mouse movement, tab presses — makes FB reveal all buttons
4. Try to find Post/Write/Join buttons and click them
5. Post to home feed as proof-of-life
"""
import json
import random
import sys
import time
import logging
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

COOKIES_DIR = Path("cookies")
SCREENSHOTS_DIR = Path("screenshots")
SCREENSHOTS_DIR.mkdir(exist_ok=True)

POST_FILE = Path("post.txt")
POST_TEXT = POST_FILE.read_text(encoding="utf-8").strip() if POST_FILE.exists() else "🧪 اختبار البوت"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [WARMUP] %(levelname)s: %(message)s")
log = logging.getLogger("warmup")


def make_driver():
    """Chrome with anti-detection so FB doesn't hide buttons."""
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1366,900")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=opts)
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": (
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                "window.chrome = {runtime: {}};"
                "Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});"
                "Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en','ar']});"
            )
        })
    except Exception as e:
        log.warning(f"Anti-detect CDP failed: {e}")
    return driver


def load_cookies(driver, path: Path):
    driver.get("https://www.facebook.com/")
    time.sleep(2)
    driver.delete_all_cookies()
    cookies = json.loads(path.read_text(encoding="utf-8"))
    count = 0
    for c in cookies:
        c.pop("sameSite", None)
        try:
            driver.add_cookie(c)
            count += 1
        except Exception as e:
            log.warning(f"Skip {c.get('name')}: {e}")
    log.info(f"🍪 Injected {count}/{len(cookies)} cookies")


def snap(driver, name: str):
    path = SCREENSHOTS_DIR / f"test_{name}.png"
    try:
        driver.save_screenshot(str(path))
        log.info(f"📸 {path.name}")
    except Exception as e:
        log.warning(f"Screenshot failed: {e}")


def warmup(driver):
    """Human-like activity so FB reveals ALL buttons (post, join, write)."""
    log.info("🔥 WARMING UP account (60-90s human activity)...")

    # Phase 1: slow scroll through feed
    log.info("   📜 Phase 1: scrolling feed")
    for i in range(6):
        px = random.randint(300, 800)
        driver.execute_script(f"window.scrollBy(0, {px})")
        log.info(f"      scroll {i+1}/6 (+{px}px)")
        time.sleep(random.uniform(2.5, 5.0))

    # Phase 2: scroll back to top slowly
    log.info("   ⬆️  Phase 2: back to top")
    for _ in range(4):
        driver.execute_script("window.scrollBy(0, -400)")
        time.sleep(random.uniform(1, 2))
    driver.execute_script("window.scrollTo(0, 0)")
    time.sleep(3)

    # Phase 3: mouse movement
    log.info("   🖱️  Phase 3: mouse movement")
    try:
        actions = ActionChains(driver)
        for _ in range(5):
            x_off = random.randint(-150, 150)
            y_off = random.randint(-100, 100)
            actions.move_by_offset(x_off, y_off).perform()
            time.sleep(random.uniform(0.4, 1.2))
    except Exception as e:
        log.warning(f"      mouse skipped: {e}")

    # Phase 4: keyboard focus (Tab keys)
    log.info("   ⌨️  Phase 4: keyboard focus")
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        for _ in range(4):
            body.send_keys(Keys.TAB)
            time.sleep(random.uniform(0.3, 0.8))
    except Exception:
        pass

    time.sleep(3)
    log.info("✅ WARMUP DONE — buttons should now be visible")


def find_first(driver, selectors, timeout=5):
    for kind, sel in selectors:
        try:
            by = By.XPATH if kind == "x" else By.CSS_SELECTOR
            el = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((by, sel))
            )
            return el, sel
        except TimeoutException:
            continue
        except Exception:
            continue
    return None, None


def scan_candidates(driver):
    """Diagnostic: find any element that might be a button."""
    try:
        return driver.execute_script("""
            const texts = ['on your mind','what','create post','create a post',
                           'share','write','join','joined','اكتب','شارك','بم تفكر',
                           'ماذا','انشر','ما الذي','انضم','الانضمام'];
            const results = [];
            const els = document.querySelectorAll('div[role="button"], button, [role="textbox"], textarea, [contenteditable="true"]');
            els.forEach((el, i) => {
                if (i > 250) return;
                const text = (el.textContent||'').trim().substring(0, 80);
                const aria = el.getAttribute('aria-label')||'';
                const placeholder = el.getAttribute('placeholder')||'';
                const combined = (text+' '+aria+' '+placeholder).toLowerCase();
                for (const t of texts) {
                    if (combined.includes(t.toLowerCase())) {
                        results.push({
                            tag: el.tagName+(el.getAttribute('role')?'['+el.getAttribute('role')+']':''),
                            text: text, aria: aria.substring(0,60),
                            placeholder: placeholder.substring(0,60),
                            visible: el.offsetParent !== null,
                        });
                        break;
                    }
                }
            });
            return results.slice(0, 20);
        """)
    except Exception as e:
        log.warning(f"DOM scan failed: {e}")
        return []


def main():
    files = sorted(COOKIES_DIR.glob("*.json"))
    if not files:
        log.error("❌ No cookies found in cookies/")
        sys.exit(1)

    log.info("=" * 50)
    log.info("🔥 WARMUP + PROFILE POST TEST")
    log.info(f"Cookies: {files[0].name}")
    log.info(f"Message: {POST_TEXT[:60]}")
    log.info("=" * 50)

    driver = make_driver()
    try:
        # 1. Login
        load_cookies(driver, files[0])
        driver.get("https://www.facebook.com/")
        time.sleep(6)

        current_url = driver.current_url
        log.info(f"URL: {current_url}")
        log.info(f"Title: {driver.title}")
        snap(driver, "1_home_before_warmup")

        if any(x in current_url.lower() for x in ["/login","/checkpoint","?next=","/challenge"]):
            log.error("❌ REDIRECTED — Account limited")
            sys.exit(1)
        log.info("✅ Home loaded (no redirect)")

        # 2. WARMUP (the core of this bot!)
        warmup(driver)
        snap(driver, "2_after_warmup")

        # 3. Find Write button (composer trigger)
        log.info("🔎 Looking for WRITE button...")
        composer, sel = find_first(driver, [
            ("x", "//div[@role='button'][.//span[contains(text(), 'on your mind')]]"),
            ("x", "//div[@role='button'][.//span[contains(text(), 'What')]]"),
            ("x", "//div[@role='button'][.//span[contains(text(), 'Create post')]]"),
            ("x", "//div[@role='button'][.//span[contains(text(), 'ما الذي يجول')]]"),
            ("x", "//div[@role='button'][.//span[contains(text(), 'بم تفكر')]]"),
            ("x", "//div[@role='button'][.//span[contains(text(), 'اكتب')]]"),
            ("x", "//div[@aria-label='Create a post']"),
            ("c", "div[aria-label*='mind' i][role='button']"),
            ("c", "div[aria-label*='post' i][role='button']"),
        ], timeout=10)

        if not composer:
            snap(driver, "3_no_write_btn")
            log.error("❌ WRITE button NOT found even after warmup")
            log.info("🔍 DOM scan for candidate buttons:")
            for i, c in enumerate(scan_candidates(driver)):
                log.info(f"  [{i+1}] {c['tag']} visible={c['visible']}")
                if c.get('text'): log.info(f"       text: {c['text']}")
                if c.get('aria'): log.info(f"       aria: {c['aria']}")
                if c.get('placeholder'): log.info(f"       placeholder: {c['placeholder']}")
            try:
                (SCREENSHOTS_DIR/"test_page_source.html").write_text(driver.page_source[:8000], encoding="utf-8")
            except Exception:
                pass
            sys.exit(1)

        log.info(f"✅ Found WRITE button: {sel[:60]}")
        composer.click()
        time.sleep(4)
        snap(driver, "3_write_opened")

        # 4. Find text area (where you actually type)
        log.info("🔎 Looking for TEXT area...")
        textarea, tsel = find_first(driver, [
            ("c", "div[role='dialog'] div[contenteditable='true'][role='textbox']"),
            ("c", "div[contenteditable='true'][data-lexical-editor='true']"),
            ("c", "div[contenteditable='true'][role='textbox']"),
        ], timeout=8)

        if not textarea:
            snap(driver, "4_no_textarea")
            log.error("❌ TEXT area NOT found")
            sys.exit(1)

        log.info(f"✅ Found TEXT area")
        textarea.click()
        time.sleep(1)
        for ch in POST_TEXT[:200]:
            textarea.send_keys(ch)
            time.sleep(random.uniform(0.03, 0.09))
        time.sleep(3)
        snap(driver, "4_text_typed")

        # 5. Find Post button
        log.info("🔎 Looking for POST button...")
        post_btn, psel = find_first(driver, [
            ("x", "//div[@aria-label='Post' and @role='button']"),
            ("x", "//div[@role='button'][.//span[text()='Post']]"),
            ("x", "//div[@role='button'][.//span[text()='نشر']]"),
            ("x", "//div[@aria-label='نشر' and @role='button']"),
        ], timeout=5)

        if not post_btn:
            snap(driver, "5_no_post_btn")
            log.error("❌ POST button NOT found")
            sys.exit(1)

        log.info(f"✅ Found POST button")
        post_btn.click()
        time.sleep(10)
        snap(driver, "5_final_posted")

        log.info("=" * 50)
        log.info("✅✅✅ SUCCESS — WARMUP + POST WORKED!")
        log.info("→ Write button: FOUND ✅")
        log.info("→ Text area: FOUND ✅")
        log.info("→ Post button: FOUND ✅")
        log.info("→ Ready to integrate warmup into poster.py + joiner.py")
        log.info("=" * 50)

    finally:
        try: driver.quit()
        except Exception: pass


if __name__ == "__main__":
    main()
