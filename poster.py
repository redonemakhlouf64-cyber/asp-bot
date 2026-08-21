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
def _is_blocked_or_redirect(driver) -> tuple[bool, str]:
    """
    Detect if Facebook redirected us to login/checkpoint instead of the group.
    Returns (True, reason) if blocked, else (False, '').
    """
    try:
        url = (driver.current_url or "").lower()
    except Exception:
        return False, ""
    if "?next=" in url:
        return True, "redirect_next"
    for marker in ["/login", "/checkpoint", "/challenge", "/recover", "/help/contact"]:
        if marker in url:
            return True, f"redirect_{marker.strip('/')}"
    try:
        title = (driver.title or "").lower()
    except Exception:
        title = ""
    if "log in" in title or "login" in title or "security check" in title:
        return True, "login_title"
    return False, ""


def _save_stage_screenshot(driver, account_id: str, group_url: str, stage: str) -> None:
    """Save a screenshot named by account, group ID, and stage."""
    try:
        SCREENSHOTS_DIR.mkdir(exist_ok=True)
        gid = group_url.rstrip("/").split("/")[-1][:14]
        path = f"screenshots/{account_id}_{gid}_{stage}.png"
        driver.save_screenshot(path)
        log.info(f"[{account_id}] 📸 {stage}: {path}")
    except Exception as e:
        log.warning(f"[{account_id}] Screenshot failed ({stage}): {e}")


def _try_join_group(driver, account_id: str) -> bool:
    """
    Click Join button if the account isn't a member yet.
    Returns True if we just joined, False if already member / no button.
    """
    for sel in [
        "div[aria-label='Join Group']",
        "div[aria-label='Join group']",
        "//span[text()='Join Group']/ancestor::div[@role='button'][1]",
        "//span[text()='Join group']/ancestor::div[@role='button'][1]",
        "//span[text()='Join']/ancestor::div[@role='button'][1]",
        "//span[contains(text(), 'انضم')]/ancestor::div[@role='button'][1]",
        "//span[contains(text(), 'الانضمام')]/ancestor::div[@role='button'][1]",
        "//span[contains(text(), 'Rejoindre')]/ancestor::div[@role='button'][1]",
    ]:
        try:
            by = By.XPATH if sel.startswith("//") else By.CSS_SELECTOR
            btn = WebDriverWait(driver, 4).until(
                EC.element_to_be_clickable((by, sel))
            )
            btn.click()
            log.info(f"[{account_id}] ✅ Clicked Join button")
            time.sleep(random.uniform(4, 7))
            return True
        except TimeoutException:
            continue
        except Exception:
            continue
    return False


def _find_composer_trigger(driver, account_id: str = "unknown"):
    """
    Try to open the composer. Returns True if we're now on a compose UI.
    Tries many selectors + languages, falls back to direct textbox,
    saves a debug screenshot if nothing works.
    """
    # Text-based XPaths (many languages)
    trigger_xpaths = [
        # English variants
        "//div[@role='button'][.//span[contains(text(), 'on your mind')]]",
        "//div[@role='button'][.//span[contains(text(), 'Write something')]]",
        "//div[@role='button'][.//span[contains(text(), 'Anything on your mind')]]",
        "//div[@role='button'][.//span[contains(text(), 'Create a post')]]",
        "//div[@role='button'][.//span[contains(text(), 'Create post')]]",
        # Arabic
        "//div[@role='button'][.//span[contains(text(), 'اكتب')]]",
        "//div[@role='button'][.//span[contains(text(), 'شارك')]]",
        "//div[@role='button'][.//span[contains(text(), 'بم تفكر')]]",
        "//div[@role='button'][.//span[contains(text(), 'ماذا يدور')]]",
        "//div[@role='button'][.//span[contains(text(), 'انشر')]]",
        # French
        "//div[@role='button'][.//span[contains(text(), 'Exprimez-vous')]]",
        "//div[@role='button'][.//span[contains(text(), 'Que voulez-vous')]]",
        "//div[@role='button'][.//span[contains(text(), 'À quoi pensez-vous')]]",
    ]
    for xp in trigger_xpaths:
        try:
            btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, xp))
            )
            btn.click()
            time.sleep(1.5)
            return True
        except TimeoutException:
            continue
        except Exception:
            continue

    # Aria-label fallbacks
    for css in [
        "div[aria-label*='Write' i][role='button']",
        "div[aria-label*='Create' i][role='button']",
        "div[aria-label*='post' i][role='button']",
    ]:
        try:
            btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, css))
            )
            btn.click()
            time.sleep(1.5)
            return True
        except TimeoutException:
            continue
        except Exception:
            continue

    # Last fallback: composer might already be a direct visible textbox
    try:
        for el in driver.find_elements(By.CSS_SELECTOR, "div[contenteditable='true'][role='textbox']"):
            try:
                if el.is_displayed():
                    el.click()
                    time.sleep(1)
                    return True
            except Exception:
                continue
    except Exception:
        pass

    # Save DEBUG screenshot so we can see what's on screen
    try:
        SCREENSHOTS_DIR.mkdir(exist_ok=True)
        gid = driver.current_url.rstrip("/").split("/")[-1][:12]
        path = f"screenshots/{account_id}_no_composer_{gid}.png"
        driver.save_screenshot(path)
        log.info(f"[{account_id}] 📸 Debug screenshot saved: {path}")
    except Exception as e:
        log.warning(f"[{account_id}] Failed to save debug screenshot: {e}")

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
    """
    Full flow per group:
    1. Enter group
    2. Handle CAPTCHA if real one appears
    3. Try to Join (silent if already member)
    4. Open composer
    5. Type post
    6. Click Post
    7. Save final screenshot
    """
    try:
        driver.get(group_url)
        human_sleep(4, 7)

        # 2. CAPTCHA (real ones only)
        solver.auto_handle(driver, account_name=account_id)

        # 2.5 Check if Facebook redirected us to login/checkpoint
        blocked, reason = _is_blocked_or_redirect(driver)
        if blocked:
            log.warning(f"[{account_id}] 🚫 BLOCKED ({reason}) — skipping: {group_url}")
            _save_stage_screenshot(driver, account_id, group_url, f"blocked_{reason}")
            return False

        # 3. Join if needed
        joined_now = _try_join_group(driver, account_id)
        if joined_now:
            _save_stage_screenshot(driver, account_id, group_url, "1_joined")
            human_sleep(6, 10)  # let join finalize

        # 4. Open composer
        if not _find_composer_trigger(driver, account_id):
            log.warning(f"[{account_id}] no_composer_trigger: {group_url}")
            _save_stage_screenshot(driver, account_id, group_url, "fail_no_composer")
            return False

        _save_stage_screenshot(driver, account_id, group_url, "2_composer_open")
        human_sleep(3, 5)

        # 5. Find textarea
        textarea = _find_textarea(driver)
        if not textarea:
            log.warning(f"[{account_id}] no_textarea: {group_url}")
            _save_stage_screenshot(driver, account_id, group_url, "fail_no_textarea")
            return False

        # 6. Type text like a human
        textarea.click()
        human_sleep(1, 2)
        for line in text.split("\n"):
            for ch in line:
                textarea.send_keys(ch)
                time.sleep(random.uniform(0.02, 0.09))
            textarea.send_keys(Keys.SHIFT + Keys.ENTER)

        _save_stage_screenshot(driver, account_id, group_url, "3_text_typed")
        human_sleep(2, 4)

        # 7. Click Post
        if _click_post_button(driver):
            human_sleep(5, 8)
            _save_stage_screenshot(driver, account_id, group_url, "4_posted")
            log.info(f"[{account_id}] ✅ Posted: {group_url}")
            return True
        else:
            log.warning(f"[{account_id}] no_post_btn: {group_url}")
            _save_stage_screenshot(driver, account_id, group_url, "fail_no_post_btn")
            return False

    except WebDriverException as e:
        log.error(f"[{account_id}] Post error on {group_url}: {e}")
        try:
            _save_stage_screenshot(driver, account_id, group_url, "fail_exception")
        except Exception:
            pass
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
