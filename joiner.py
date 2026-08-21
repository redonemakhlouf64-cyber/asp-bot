"""
joiner.py
==========
Cookie-based Facebook group joiner.
Reads cookies/*.json, injects into Chrome, joins groups.
No email/password. No login form. Fully automatic.
"""

import os
import json
import time
import random
import logging
import traceback
from pathlib import Path
from typing import List, Optional

from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from device_profiles import get_driver_for_account
from captcha_auto import AutoCaptchaSolver

# ===================================================================
# LOGGING
# ===================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [JOINER] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler("joiner.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ===================================================================
# CONFIG
# ===================================================================
COOKIES_DIR = Path("cookies")           # folder with account_XX.json files
GROUPS_FILE = Path("groups.txt")        # one group URL per line
JOINED_FILE = Path("state/joined.json") # remembers what each account joined

HEADLESS = True
MIN_DELAY, MAX_DELAY = 3, 8
GROUP_COOLDOWN = (60, 180)              # wait between groups
ACCOUNT_COOLDOWN = (120, 300)           # wait between accounts

solver = AutoCaptchaSolver()


# ===================================================================
# HELPERS
# ===================================================================
def human_sleep(a: float = MIN_DELAY, b: float = MAX_DELAY) -> None:
    time.sleep(random.uniform(a, b))


def load_groups() -> List[str]:
    if not GROUPS_FILE.exists():
        log.error(f"{GROUPS_FILE} not found")
        return []
    return [
        line.strip() for line in GROUPS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def list_accounts() -> List[str]:
    """Return account IDs from cookies/*.json filenames."""
    if not COOKIES_DIR.exists():
        log.error(f"{COOKIES_DIR}/ folder not found")
        return []
    return sorted(f.stem for f in COOKIES_DIR.glob("*.json"))


def load_joined_state() -> dict:
    if JOINED_FILE.exists():
        try:
            return json.loads(JOINED_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_joined_state(state: dict) -> None:
    JOINED_FILE.parent.mkdir(parents=True, exist_ok=True)
    JOINED_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ===================================================================
# COOKIE INJECTION
# ===================================================================
def inject_cookies(driver, account_id: str) -> bool:
    """
    Load cookies/<account_id>.json and inject into the driver.
    Supports both Cookie-Editor format and EditThisCookie format.
    """
    cookie_file = COOKIES_DIR / f"{account_id}.json"
    if not cookie_file.exists():
        log.error(f"[{account_id}] Cookie file not found: {cookie_file}")
        return False

    try:
        raw = json.loads(cookie_file.read_text(encoding="utf-8"))

        # Handle both {"cookies": [...]} and just [...]
        cookies = raw.get("cookies", raw) if isinstance(raw, dict) else raw
        if not isinstance(cookies, list):
            log.error(f"[{account_id}] Bad cookie format")
            return False

        # Must be on facebook.com before adding cookies
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
            except Exception as e:
                log.debug(f"[{account_id}] Skipped cookie {cookie['name']}: {e}")

        log.info(f"[{account_id}] Injected {added} cookies")
        return added > 0

    except Exception as e:
        log.error(f"[{account_id}] Cookie injection failed: {e}")
        return False


def verify_logged_in(driver, account_id: str) -> bool:
    """Reload facebook.com and check we're not on the login page."""
    driver.get("https://www.facebook.com/")
    human_sleep(3, 5)

    url = driver.current_url.lower()
    if "login" in url or "checkpoint" in url:
        log.warning(f"[{account_id}] Cookies invalid / expired")
        return False

    try:
        driver.find_element(By.CSS_SELECTOR, "[aria-label='Your profile'], [aria-label='Account']")
    except Exception:
        pass

    log.info(f"[{account_id}] ✅ Logged in via cookies")
    return True


# ===================================================================
# JOIN GROUP
# ===================================================================
def join_group(driver, group_url: str, account_id: str) -> bool:
    try:
        driver.get(group_url)
        human_sleep()

        # Auto-solve any CAPTCHA if it shows
        solver.auto_handle(driver, account_name=account_id)

        for sel in [
            "div[aria-label='Join Group']",
            "div[aria-label='Join group']",
            "//span[text()='Join Group']/ancestor::div[@role='button'][1]",
            "//span[text()='Join group']/ancestor::div[@role='button'][1]",
            "//span[contains(text(),'Join')]/ancestor::div[@role='button'][1]",
        ]:
            try:
                by = By.XPATH if sel.startswith("//") else By.CSS_SELECTOR
                btn = WebDriverWait(driver, 6).until(
                    EC.element_to_be_clickable((by, sel))
                )
                btn.click()
                human_sleep(2, 4)
                log.info(f"[{account_id}] ✅ Joined {group_url}")
                return True
            except TimeoutException:
                continue
            except Exception:
                continue

        log.info(f"[{account_id}] Already member or no Join btn: {group_url}")
        return True

    except WebDriverException as e:
        log.error(f"[{account_id}] Join error on {group_url}: {e}")
        return False


# ===================================================================
# PER-ACCOUNT FLOW
# ===================================================================
def process_account(account_id: str, groups: List[str], joined_state: dict) -> None:
    driver = None
    already = set(joined_state.get(account_id, []))
    to_join = [g for g in groups if g not in already]

    if not to_join:
        log.info(f"[{account_id}] Nothing new to join, skipping")
        return

    try:
        log.info(f"[{account_id}] Session starting ({len(to_join)} new groups)")
        driver = get_driver_for_account(account_id, headless=HEADLESS)

        if not inject_cookies(driver, account_id):
            return
        if not verify_logged_in(driver, account_id):
            return

        for group_url in to_join:
            if join_group(driver, group_url, account_id):
                already.add(group_url)
                joined_state[account_id] = sorted(already)
                save_joined_state(joined_state)
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

    if not accounts:
        log.error("No cookies in cookies/ folder — add account_XX.json files")
        return
    if not groups:
        log.error("No groups in groups.txt")
        return

    log.info(f"🚀 Starting — {len(accounts)} accounts, {len(groups)} groups")
    joined_state = load_joined_state()

    for account_id in accounts:
        try:
            process_account(account_id, groups, joined_state)
        except KeyboardInterrupt:
            log.info("Interrupted by user")
            break
        except Exception as e:
            log.error(f"[{account_id}] Unhandled: {e}")
            continue

        time.sleep(random.uniform(*ACCOUNT_COOLDOWN))

    log.info("🏁 Done — sleep well!")


if __name__ == "__main__":
    main()
