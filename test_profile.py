"""
test_profile.py — Quick health test.
Tries to post to Facebook home feed (profile timeline).
If it works: account is healthy, cookies work, UI works.
If it fails: account is limited OR cookies expired.
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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

COOKIES_DIR = Path("cookies")
SCREENSHOTS_DIR = Path("screenshots")
SCREENSHOTS_DIR.mkdir(exist_ok=True)

POST_FILE = Path("post.txt")
POST_TEXT = POST_FILE.read_text(encoding="utf-8").strip() if POST_FILE.exists() else "🧪 اختبار البوت"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [TEST] %(levelname)s: %(message)s")
log = logging.getLogger("test")


def make_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1366,900")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(options=opts)


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


def main():
    files = sorted(COOKIES_DIR.glob("*.json"))
    if not files:
        log.error("❌ No cookies found in cookies/")
        sys.exit(1)

    log.info("=" * 50)
    log.info("🧪 PROFILE POST TEST")
    log.info(f"Cookies: {files[0].name}")
    log.info(f"Message: {POST_TEXT[:60]}")
    log.info("=" * 50)

    driver = make_driver()
    try:
        # 1. Login via cookies
        load_cookies(driver, files[0])
        driver.get("https://www.facebook.com/")
        time.sleep(6)

        current_url = driver.current_url
        title = driver.title
        log.info(f"URL: {current_url}")
        log.info(f"Title: {title}")
        snap(driver, "1_home")

        # 2. Check for redirect
        if any(x in current_url.lower() for x in ["/login", "/checkpoint", "?next=", "/challenge"]):
            log.error("❌❌❌ REDIRECTED to auth page")
            log.error(f"→ URL: {current_url}")
            log.error("→ DIAGNOSIS: Account is limited / needs verification")
            log.error("→ FIX: Get fresh cookies OR use different account")
            sys.exit(1)

        log.info("✅ Home feed loaded (no redirect)")

        # 3. Find composer trigger
        composer, sel = find_first(driver, [
            ("x", "//div[@role='button'][.//span[contains(text(), 'on your mind')]]"),
            ("x", "//div[@role='button'][.//span[contains(text(), 'ما الذي يجول')]]"),
            ("x", "//div[@role='button'][.//span[contains(text(), 'بم تفكر')]]"),
            ("x", "//div[@role='button'][.//span[contains(text(), 'اكتب')]]"),
            ("c", "div[aria-label*='mind' i][role='button']"),
        ], timeout=8)

        if not composer:
            snap(driver, "2_no_composer")
            log.error("❌ Composer NOT found with standard selectors")
            log.error("🔍 Running deep DOM scan...")

            # DIAGNOSTIC: scan all buttons/spans for likely composer text
            try:
                candidates = driver.execute_script("""
                    const texts = ['on your mind', 'what', 'create post', 'create a post',
                                   'share', 'write something', 'anything on',
                                   'اكتب', 'شارك', 'بم تفكر', 'ماذا', 'انشر', 'ما الذي'];
                    const results = [];
                    const els = document.querySelectorAll('div[role="button"], button, [role="textbox"], textarea, [contenteditable="true"]');
                    els.forEach((el, i) => {
                        if (i > 200) return;
                        const text = (el.textContent || '').trim().substring(0, 80);
                        const aria = el.getAttribute('aria-label') || '';
                        const placeholder = el.getAttribute('placeholder') || '';
                        const combined = (text + ' ' + aria + ' ' + placeholder).toLowerCase();
                        for (const t of texts) {
                            if (combined.includes(t.toLowerCase())) {
                                results.push({
                                    tag: el.tagName + (el.getAttribute('role') ? '[' + el.getAttribute('role') + ']' : ''),
                                    text: text,
                                    aria: aria.substring(0, 60),
                                    placeholder: placeholder.substring(0, 60),
                                    visible: el.offsetParent !== null,
                                });
                                break;
                            }
                        }
                    });
                    return results.slice(0, 15);
                """)
                log.info(f"🔍 Found {len(candidates)} candidate elements:")
                for i, c in enumerate(candidates):
                    log.info(f"  [{i+1}] {c['tag']} visible={c['visible']}")
                    if c.get('text'):
                        log.info(f"       text: {c['text']}")
                    if c.get('aria'):
                        log.info(f"       aria-label: {c['aria']}")
                    if c.get('placeholder'):
                        log.info(f"       placeholder: {c['placeholder']}")
            except Exception as e:
                log.warning(f"DOM scan failed: {e}")

            # Save HTML snippet for further debugging
            try:
                html = driver.page_source[:5000]
                (SCREENSHOTS_DIR / "test_page_source.html").write_text(html, encoding="utf-8")
                log.info("📄 Saved first 5000 chars of HTML")
            except Exception as e:
                log.warning(f"HTML save failed: {e}")

            sys.exit(1)

        log.info(f"✅ Found composer: {sel[:60]}")
        composer.click()
        time.sleep(4)
        snap(driver, "2_composer_open")

        # 4. Find textarea
        textarea, tsel = find_first(driver, [
            ("c", "div[role='dialog'] div[contenteditable='true'][role='textbox']"),
            ("c", "div[contenteditable='true'][data-lexical-editor='true']"),
            ("c", "div[contenteditable='true'][role='textbox']"),
        ], timeout=8)

        if not textarea:
            snap(driver, "3_no_textarea")
            log.error("❌ Textarea NOT found")
            sys.exit(1)

        log.info(f"✅ Found textarea")
        textarea.click()
        time.sleep(1)

        # 5. Type message
        for ch in POST_TEXT[:200]:
            textarea.send_keys(ch)
            time.sleep(random.uniform(0.03, 0.09))

        time.sleep(3)
        snap(driver, "3_text_typed")

        # 6. Find Post button
        post_btn, psel = find_first(driver, [
            ("x", "//div[@aria-label='Post' and @role='button']"),
            ("x", "//div[@role='button'][.//span[text()='Post']]"),
            ("x", "//div[@role='button'][.//span[text()='نشر']]"),
        ], timeout=5)

        if not post_btn:
            snap(driver, "4_no_post_btn")
            log.error("❌ Post button NOT found")
            sys.exit(1)

        log.info(f"✅ Found Post btn")
        post_btn.click()
        time.sleep(10)
        snap(driver, "4_final")

        log.info("=" * 50)
        log.info("✅✅✅ TEST PASSED — Posted to profile!")
        log.info("→ Account is HEALTHY")
        log.info("→ If groups fail, issue is group-specific")
        log.info("=" * 50)

    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
