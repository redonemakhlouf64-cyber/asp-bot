"""
poster.py
==========
Cookie-based Facebook group poster.
Reads cookies/*.json, injects into Chrome, posts to groups.
No email/password. No login form. Fully automatic.
"""

import json
import time
import random
import logging
import traceback
from pathlib import Path
from typing import List

from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from device_profiles import get_driver_for_account
from captcha_auto import AutoCaptchaSolver

# ===================================================================
# LOGGING
# ===================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [POSTER] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler("poster.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ===================================================================
# CONFIG
# ===================================================================
COOKIES_DIR = Path("cookies")
GROUPS_FILE = Path("groups.txt")
POST_FILE = Path("post.txt")
POSTED_FILE = Path("state/posted.json")
SCREENSHOTS_DIR = Path("screenshots")

HEADLESS = True
MIN_DELAY, MAX_DELAY = 3, 8
GROUP_COOLDOWN = (60, 180)      # wait between groups per account
ACCOUNT_COOLDOWN = (120, 300)   # wait between accounts
POSTS_PER_ACCOUNT_LIMIT = 15    # safety cap per run (avoid spam-flag)

solver = AutoCaptchaSolver()


# ===================================================================
# HELPERS
# ===================================================================
def human_sleep(a: float = MIN_DELAY, b: float = MAX_DELAY) -> None:
    time.sleep(random.uniform(a, b))


def load_post_text() -> str:
    if not POST_FILE.exists():
        log.error(f"{POST_FILE} not found — create it with your post text")
        return ""
    return POST_FILE.read_text(encoding="utf-8").strip()


def load_groups() -> List[str]:
    if not GROUPS_FILE.exists():
        log.error(f"{GROUPS_FILE} not found")
        return []
    return [
        line.strip() for line in GROUPS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def list_accounts() -> List[str]:
    if not COOKIES_DIR.exists():
        log.error(f"{COOKIES_DIR}/ folder not found")
        return []
    return sorted(f.stem for f in COOKIES_DIR.glob("*.json"))


def load_posted_state() -> dict:
    if POSTED_FILE.exists():
        try:
            return json.loads(POSTED_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_posted_state(state: dict) -> None:
    POSTED_FILE.parent.mkdir(parents=True, exist_ok=True)
    POSTED_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ===================================================================
# COOKIE INJECTION (same as joiner)
# ===================================================================
def inject_cookies(driver, account_id: str) -> bool:
    cookie_file = COOKIES_DIR / f"{account_id}.json"
    if not cookie_file.exists():
        log.error(f"[{account_id}] Cookie file not found: {cookie_file}")
        return False

    try:
        raw = json.loads(cookie_file.read_text(encoding="utf-8"))
        cookies = raw.get("cookies", raw) if isinstance(raw, dict) else raw
        if not isinstance(cookies, list):
            return False

        driver.get("https://www.facebook.com/")
        time.sleep(2)
        driver.delete_all_cookies()

        added = 0
        for c in cookies:
            cookie = {
                "name":   c.get("name"),
                "value":  c.get("value"),
                "domain": c.get("domain", ".facebook.com"),
                "path":   c.get("path", "/"),
                "secure": c.get("secure", True),
            }
            if "httpOnly" in c: cookie["httpOnly"] = c["httpOnly"]
            if "sameSite" in c and c["sameSite"] in ("Strict", "Lax", "None"):
                cookie["sameSite"] = c["sameSite"]
            if "expirationDate" in c:
                cookie["expiry"] = int(c["expirationDate"])
            elif "expiry" in c:
                cookie["expiry"] = int(c["expiry"])

            if not cookie["name"] or cookie["value"] is None:
                continue

            try:
                driver.add_cookie(cookie)
                added += 1
            except Exception:
                pass

        log.info(f"[{account_id}] Injected {added} cookies")
        return added > 0

    except Exception as e:
        log.error(f"[{account_id}] Cookie injection failed: {e}")
        return False


def verify_logged_in(driver, account_id: str) -> bool:
    driver.get("https://www.facebook.com/")
    human_sleep(3, 5)

    url = driver.current_url.lower()
    if "login" in url or "checkpoint" in url:
        log.warning(f"[{account_id}] Cookies invalid / expired")
        return False

    log.info(f"[{account_id}] ✅ Logged in via cookies")
    return True


# ===================================================================
# POST TO GROUP
# ===================================================================
def _find_composer_trigger(driver):
    """Click the 'Write something...' trigger to open the modal."""
    for sel in [
        "//div[@role='button' and (contains(., 'Write something') or contains(., 'Anything on your mind'))]",
        "//span[contains(text(), 'Write something')]/ancestor::div[@role='button'][1]",
        "//span[contains(text(), 'اكتب شيئا')]/ancestor::div[@role='button'][1]",
        "//span[contains(text(), 'شارك أفكارك')]/ancestor::div[@role='button'][1]",
        "div[aria-label*='Write something' i]",
        "div[aria-label*='Create a post' i]",
    ]:
        try:
            by = By.XPATH if sel.startswith("//") else By.CSS_SELECTOR
            btn = WebDriverWait(driver, 6).until(
                EC.element_to_be_clickable((by, sel))
            )
            btn.click()
            return True
        except TimeoutException:
            continue
        except Exception:
            continue
    return False


def _find_textarea(driver):
    """Locate the contenteditable composer inside the modal."""
    for sel in [
        "div[role='dialog'] div[contenteditable='true'][role='textbox']",
        "div[contenteditable='true'][data-lexical-editor='true']",
        "div[role='textbox'][contenteditable='true']",
    ]:
        try:
            return WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel))
            )
        except TimeoutException:
            continue
    return None


def _click_post_button(driver):
    for sel in [
        "//div[@aria-label='Post' and @role='button']",
        "//span[text()='Post']/ancestor::div[@role='button'][1]",
        "//span[text()='نشر']/ancestor::div[@role='button'][1]",
        "//div[@role='button'][.//span[text()='Post']]",
    ]:
        try:
            btn = WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable((By.XPATH, sel))
            )
            btn.click()
            return True
        except TimeoutException:
            continue
        except Exception:
            continue
    return False


def post_to_group(driver, group_url: str, text: str, account_id: str) -> bool:
    try:
        driver.get(group_url)
        human_sleep(4, 7)

        solver.auto_handle(driver, account_name=account_id)

        if not _find_composer_trigger(driver):
            log.warning(f"[{account_id}] no_composer_trigger: {group_url}")
            return False

        human_sleep(3, 5)
        textarea = _find_textarea(driver)
        if not textarea:
            log.warning(f"[{account_id}] no_textarea: {group_url}")
            return False

        # Type text like a human (character-by-character)
        textarea.click()
        human_sleep(1, 2)
        for line in text.split("\n"):
            for ch in line:
                textarea.send_keys(ch)
                time.sleep(random.uniform(0.02, 0.09))
            textarea.send_keys(Keys.SHIFT + Keys.ENTER)

        human_sleep(2, 4)

        if _click_post_button(driver):
            human_sleep(5, 8)
            log.info(f"[{account_id}] ✅ Posted: {group_url}")
            return True
        else:
            log.warning(f"[{account_id}] no_post_btn: {group_url}")
            return False

    except WebDriverException as e:
        log.error(f"[{account_id}] Post error on {group_url}: {e}")
        return False


# ===================================================================
# PER-ACCOUNT FLOW
# ===================================================================
def process_account(account_id: str, groups: List[str], text: str, posted_state: dict) -> None:
    driver = None
    posted_here = set(posted_state.get(account_id, []))
    to_post = [g for g in groups if g not in posted_here]

    if not to_post:
        log.info(f"[{account_id}] Nothing new to post")
        return

    to_post = to_post[:POSTS_PER_ACCOUNT_LIMIT]

    try:
        log.info(f"[{account_id}] Session starting ({len(to_post)} groups)")
        driver = get_driver_for_account(account_id, headless=HEADLESS)

        if not inject_cookies(driver, account_id):
            return
        if not verify_logged_in(driver, account_id):
            return

        # Proof-of-login screenshot
        try:
            SCREENSHOTS_DIR.mkdir(exist_ok=True)
            driver.save_screenshot(f"screenshots/{account_id}_poster_login.png")
            log.info(f"[{account_id}] 📸 Screenshot saved")
        except Exception:
            pass

        for group_url in to_post:
            if post_to_group(driver, group_url, text, account_id):
                posted_here.add(group_url)
                posted_state[account_id] = sorted(posted_here)
                save_posted_state(posted_state)
            time.sleep(random.uniform(*GROUP_COOLDOWN))

        log.info(f"[{account_id}] ✅ Session complete")

    except Exception as e:
        log.error(f"[{account_id}] Fatal: {e}")
        log.debug(traceback.format_exc())
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ===================================================================
# MAIN
# ===================================================================
def main() -> None:
    accounts = list_accounts()
    groups = load_groups()
    text = load_post_text()

    if not accounts:
        log.error("No cookies in cookies/ folder")
        return
    if not groups:
        log.error("No groups in groups.txt")
        return
    if not text:
        log.error("No post text in post.txt")
        return

    log.info(f"🚀 Starting — {len(accounts)} accounts, {len(groups)} groups, text: {len(text)} chars")
    posted_state = load_posted_state()

    for account_id in accounts:
        try:
            process_account(account_id, groups, text, posted_state)
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error(f"[{account_id}] Unhandled: {e}")
            continue
        time.sleep(random.uniform(*ACCOUNT_COOLDOWN))

    log.info("🏁 Done — sleep well!")


if __name__ == "__main__":
    main()
