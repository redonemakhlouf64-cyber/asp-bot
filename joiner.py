"""
joiner.py
==========
Full production bot: loops accounts, uses device profiles,
solves CAPTCHAs automatically, joins groups, handles errors.
100%% automatic — no manual work, no Telegram.
"""

import os
import time
import random
import logging
import traceback
from typing import List

from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
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
ACCOUNTS = [
    # (account_id, email, password)
    ("account_01", "user1@example.com", "password1"),
    ("account_02", "user2@example.com", "password2"),
    ("account_03", "user3@example.com", "password3"),
]

GROUPS_TO_JOIN = [
    "https://www.facebook.com/groups/example1",
    "https://www.facebook.com/groups/example2",
]

HEADLESS = True
MIN_DELAY = 3   # seconds between actions
MAX_DELAY = 8
GROUP_COOLDOWN = (60, 180)  # random wait between groups per account

solver = AutoCaptchaSolver()


# ===================================================================
# HELPERS
# ===================================================================
def human_sleep(a: int = MIN_DELAY, b: int = MAX_DELAY) -> None:
    """Random delay to look human."""
    time.sleep(random.uniform(a, b))


def safe_find(driver, by, value, timeout: int = 15):
    """Wait for element or return None (no exception)."""
    try:
        return WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )
    except TimeoutException:
        return None


# ===================================================================
# ACCOUNT WORKFLOW
# ===================================================================
def login(driver, email: str, password: str, account_id: str) -> bool:
    """Login flow with auto CAPTCHA handling."""
    try:
        driver.get("https://www.facebook.com/login")
        human_sleep()

        email_input = safe_find(driver, By.ID, "email")
        pass_input = safe_find(driver, By.ID, "pass")
        if not email_input or not pass_input:
            log.warning(f"[{account_id}] Login form not found")
            return False

        email_input.clear()
        email_input.send_keys(email)
        human_sleep(1, 2)

        pass_input.clear()
        pass_input.send_keys(password)
        human_sleep(1, 2)

        login_btn = safe_find(driver, By.NAME, "login", timeout=5)
        if login_btn:
            login_btn.click()

        human_sleep(4, 6)

        # Auto-solve any CAPTCHA/checkpoint
        if not solver.auto_handle(driver, account_name=account_id):
            log.warning(f"[{account_id}] CAPTCHA failed on login")
            return False

        # Verify login succeeded
        if "login" in driver.current_url or "checkpoint" in driver.current_url:
            log.warning(f"[{account_id}] Still on login/checkpoint page")
            return False

        log.info(f"[{account_id}] ✅ Logged in")
        return True

    except WebDriverException as e:
        log.error(f"[{account_id}] Login error: {e}")
        return False


def join_group(driver, group_url: str, account_id: str) -> bool:
    """Navigate to a group and click Join. Handles CAPTCHA if it shows."""
    try:
        driver.get(group_url)
        human_sleep()

        # CAPTCHA might appear here
        if not solver.auto_handle(driver, account_name=account_id):
            log.warning(f"[{account_id}] CAPTCHA failed on {group_url}")
            return False

        # Try to click Join button (several possible selectors)
        for sel in [
            "div[aria-label='Join Group']",
            "div[aria-label='Join group']",
            "//span[text()='Join Group']/ancestor::div[@role='button'][1]",
            "//span[text()='Join group']/ancestor::div[@role='button'][1]",
        ]:
            try:
                by = By.XPATH if sel.startswith("//") else By.CSS_SELECTOR
                btn = WebDriverWait(driver, 8).until(
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

        log.info(f"[{account_id}] Already a member or no button: {group_url}")
        return True

    except WebDriverException as e:
        log.error(f"[{account_id}] Join error on {group_url}: {e}")
        return False


def process_account(account_id: str, email: str, password: str,
                    groups: List[str]) -> None:
    """Full flow for one account. Never raises — always cleans up."""
    driver = None
    try:
        log.info(f"[{account_id}] Starting session")
        driver = get_driver_for_account(account_id, headless=HEADLESS)

        if not login(driver, email, password, account_id):
            log.warning(f"[{account_id}] Skipping — will retry next cycle")
            return

        for group_url in groups:
            join_group(driver, group_url, account_id)
            time.sleep(random.uniform(*GROUP_COOLDOWN))

        log.info(f"[{account_id}] ✅ Session complete")

    except Exception as e:
        log.error(f"[{account_id}] Fatal error: {e}")
        log.debug(traceback.format_exc())
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ===================================================================
# MAIN LOOP
# ===================================================================
def main() -> None:
    log.info(f"🚀 Starting joiner — {len(ACCOUNTS)} accounts, {len(GROUPS_TO_JOIN)} groups")

    for account_id, email, password in ACCOUNTS:
        try:
            process_account(account_id, email, password, GROUPS_TO_JOIN)
        except KeyboardInterrupt:
            log.info("Interrupted by user")
            break
        except Exception as e:
            log.error(f"[{account_id}] Unhandled: {e}")
            continue

        # Cool-down between accounts (looks natural)
        time.sleep(random.uniform(120, 300))

    log.info("🏁 All accounts done — sleep well!")


if __name__ == "__main__":
    main()
