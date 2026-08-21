"""
test_profile.py — Mobile Facebook (mbasic) posting test.
Uses mbasic.facebook.com — simple HTML without JavaScript.
Much easier for automation: standard textarea + submit button.
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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

COOKIES_DIR = Path("cookies")
SCREENSHOTS_DIR = Path("screenshots")
SCREENSHOTS_DIR.mkdir(exist_ok=True)

POST_FILE = Path("post.txt")
POST_TEXT = POST_FILE.read_text(encoding="utf-8").strip() if POST_FILE.exists() else "🧪 اختبار البوت"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [MOBILE] %(levelname)s: %(message)s")
log = logging.getLogger("mobile")


def make_driver():
    """Chrome with mobile UA to render mbasic simplified HTML."""
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=414,896")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
    )
    return webdriver.Chrome(options=opts)


def load_cookies(driver, path: Path):
    # Cookies were exported from .facebook.com, work on any subdomain
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
    path = SCREENSHOTS_DIR / f"mobile_{name}.png"
    try:
        driver.save_screenshot(str(path))
        log.info(f"📸 {path.name}")
    except Exception as e:
        log.warning(f"Screenshot failed: {e}")


def find_el(driver, selectors, timeout=5, clickable=True):
    for kind, sel in selectors:
        try:
            by = By.XPATH if kind == "x" else By.CSS_SELECTOR
            cond = EC.element_to_be_clickable if clickable else EC.presence_of_element_located
            el = WebDriverWait(driver, timeout).until(cond((by, sel)))
            return el, sel
        except TimeoutException:
            continue
        except Exception:
            continue
    return None, None


def main():
    files = sorted(COOKIES_DIR.glob("*.json"))
    if not files:
        log.error("❌ No cookies found")
        sys.exit(1)

    log.info("=" * 50)
    log.info("📱 MBASIC FACEBOOK POST TEST")
    log.info(f"Cookies: {files[0].name}")
    log.info(f"Message: {POST_TEXT[:60]}")
    log.info("=" * 50)

    driver = make_driver()
    try:
        # 1. Inject cookies via www then navigate to mbasic
        load_cookies(driver, files[0])

        log.info("🌐 Loading mbasic.facebook.com...")
        driver.get("https://mbasic.facebook.com/")
        time.sleep(5)

        current_url = driver.current_url
        log.info(f"URL: {current_url}")
        log.info(f"Title: {driver.title}")
        snap(driver, "1_home")

        if any(x in current_url.lower() for x in ["/login", "/checkpoint", "/help", "?next="]):
            log.error("❌ Redirected — cookies expired/account limited")
            log.error(f"→ {current_url}")
            sys.exit(1)

        log.info("✅ mbasic home loaded")

        # 2. Find composer textarea on home page
        log.info("🔎 Looking for TEXTAREA...")
        textarea, tsel = find_el(driver, [
            ("c", "textarea[name='xc_message']"),
            ("c", "form[action*='composer'] textarea"),
            ("c", "form textarea"),
            ("c", "textarea"),
        ], timeout=5, clickable=False)

        if not textarea:
            log.warning("⚠️  No textarea on home. Trying direct composer URL...")
            driver.get("https://mbasic.facebook.com/composer/")
            time.sleep(4)
            snap(driver, "2b_composer_page")
            log.info(f"URL now: {driver.current_url}")

            textarea, tsel = find_el(driver, [
                ("c", "textarea[name='xc_message']"),
                ("c", "form textarea"),
                ("c", "textarea"),
            ], timeout=5, clickable=False)

        if not textarea:
            snap(driver, "3_no_textarea_anywhere")
            log.error("❌ No textarea found ANYWHERE")
            log.info("📄 Page HTML (first 3000 chars):")
            try:
                html = driver.page_source[:3000]
                for line in html.split("\n")[:60]:
                    log.info(f"  {line}")
                (SCREENSHOTS_DIR / "mobile_page.html").write_text(driver.page_source[:20000], encoding="utf-8")
            except Exception as e:
                log.warning(f"HTML dump failed: {e}")
            sys.exit(1)

        log.info(f"✅ Found textarea: {tsel}")

        # 3. Type the message
        textarea.click()
        time.sleep(1)
        textarea.send_keys(POST_TEXT)
        time.sleep(2)
        snap(driver, "3_text_typed")

        # 4. Find submit/Post button
        log.info("🔎 Looking for POST/SUBMIT button...")
        post_btn, psel = find_el(driver, [
            ("c", "input[type='submit'][value='Post']"),
            ("c", "button[type='submit'][name='view_post']"),
            ("x", "//input[@type='submit' and (@value='Post' or @value='نشر' or @value='Publier')]"),
            ("x", "//button[@type='submit' and (contains(., 'Post') or contains(., 'نشر'))]"),
            ("c", "form input[type='submit']"),
            ("c", "form button[type='submit']"),
        ], timeout=5)

        if not post_btn:
            snap(driver, "4_no_post_btn")
            log.error("❌ No Post/Submit button found")
            sys.exit(1)

        log.info(f"✅ Found Post button: {psel}")
        post_btn.click()
        time.sleep(8)
        snap(driver, "5_final")

        log.info("=" * 50)
        log.info("✅✅✅ POSTED VIA MBASIC!")
        log.info("→ Mobile approach works!")
        log.info("→ We can now rewrite poster.py + joiner.py with mbasic")
        log.info("=" * 50)

    finally:
        try: driver.quit()
        except Exception: pass


if __name__ == "__main__":
    main()
