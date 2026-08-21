"""
anti_detection.py
==================
Make Selenium look like a real human browser.
- Hides webdriver signals
- Randomizes fingerprint
- Simulates human mouse/keyboard
- Rotates user agents
- Adds realistic delays
"""

import os
import time
import random
import logging
from typing import Optional

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.keys import Keys
except ImportError:
    raise ImportError("Run: pip install selenium")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ANTI-DETECT] %(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)


# ===================================================================
# USER AGENT ROTATION
# ===================================================================
def load_user_agents(path: str = "user_agents.txt") -> list:
    """Load user agents from file (skipping comments/blank lines)."""
    if not os.path.exists(path):
        log.warning(f"{path} not found. Using default.")
        return [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        ]
    with open(path, "r", encoding="utf-8") as f:
        return [
            line.strip()
            for line in f
            if line.strip() and not line.startswith("#")
        ]


def get_random_user_agent(path: str = "user_agents.txt") -> str:
    """Pick a random user agent."""
    agents = load_user_agents(path)
    return random.choice(agents)


# ===================================================================
# STEALTH CHROME
# ===================================================================
def create_stealth_driver(
    headless: bool = True,
    user_agent: Optional[str] = None,
    proxy: Optional[str] = None,
    window_size: tuple = (1366, 768),
) -> webdriver.Chrome:
    """Create a Chrome driver that is very hard to detect as a bot."""

    options = Options()

    # --- Basic stealth ---
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # --- Common flags ---
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument(f"--window-size={window_size[0]},{window_size[1]}")

    # --- Language & locale (English-speaking) ---
    options.add_argument("--lang=en-US")
    options.add_experimental_option("prefs", {
        "intl.accept_languages": "en-US,en",
        "profile.default_content_setting_values.notifications": 2,
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
    })

    # --- User Agent ---
    ua = user_agent or get_random_user_agent()
    options.add_argument(f"--user-agent={ua}")
    log.info(f"Using UA: {ua[:60]}...")

    # --- Headless ---
    if headless:
        options.add_argument("--headless=new")

    # --- Proxy ---
    if proxy:
        options.add_argument(f"--proxy-server={proxy}")
        log.info(f"Using proxy: {proxy}")

    # --- Create driver ---
    driver = webdriver.Chrome(options=options)

    # --- Inject stealth JS ---
    _apply_stealth_scripts(driver)

    log.info("Stealth driver ready")
    return driver


def _apply_stealth_scripts(driver) -> None:
    """Inject JavaScript to hide webdriver traces."""

    # Remove `navigator.webdriver`
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // Fake plugins array
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            // Fake languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });

            // Fake chrome runtime
            window.chrome = { runtime: {} };

            // Permissions query fix
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
            );

            // Fake platform
            Object.defineProperty(navigator, 'platform', {
                get: () => 'Win32'
            });

            // Fake hardwareConcurrency
            Object.defineProperty(navigator, 'hardwareConcurrency', {
                get: () => 8
            });

            // Fake deviceMemory
            Object.defineProperty(navigator, 'deviceMemory', {
                get: () => 8
            });
            """
        },
    )


# ===================================================================
# HUMAN-LIKE BEHAVIOR
# ===================================================================
def human_delay(min_s: float = 1.5, max_s: float = 4.5) -> None:
    """Random delay to look human."""
    time.sleep(random.uniform(min_s, max_s))


def human_type(element, text: str, min_delay: float = 0.05, max_delay: float = 0.25) -> None:
    """Type text with realistic per-character delays."""
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(min_delay, max_delay))
        # Occasional pause (thinking)
        if random.random() < 0.05:
            time.sleep(random.uniform(0.3, 1.2))


def human_scroll(driver, min_scrolls: int = 2, max_scrolls: int = 6) -> None:
    """Scroll the page like a human (multiple small scrolls)."""
    count = random.randint(min_scrolls, max_scrolls)
    for _ in range(count):
        scroll_by = random.randint(200, 700)
        driver.execute_script(f"window.scrollBy(0, {scroll_by});")
        time.sleep(random.uniform(0.5, 2.0))


def human_mouse_move(driver, element=None) -> None:
    """Move mouse in a realistic pattern."""
    actions = ActionChains(driver)
    if element:
        # Move to element with slight offset
        offset_x = random.randint(-5, 5)
        offset_y = random.randint(-5, 5)
        actions.move_to_element_with_offset(element, offset_x, offset_y)
    else:
        # Random movement across screen
        for _ in range(random.randint(2, 5)):
            x = random.randint(50, 800)
            y = random.randint(50, 500)
            actions.move_by_offset(x, y)
            actions.pause(random.uniform(0.1, 0.4))
    actions.perform()


def random_page_action(driver) -> None:
    """Perform a random idle action (scroll, mouse move, or wait)."""
    action = random.choice(["scroll", "mouse", "wait", "scroll"])
    if action == "scroll":
        human_scroll(driver, 1, 3)
    elif action == "mouse":
        try:
            human_mouse_move(driver)
        except Exception:
            pass
    else:
        human_delay(2, 5)


# ===================================================================
# CHECKPOINT / BAN DETECTION
# ===================================================================
CHECKPOINT_INDICATORS = [
    "checkpoint",
    "suspicious activity",
    "confirm your identity",
    "account temporarily locked",
    "we've suspended your account",
    "security check",
    "unusual login",
]


def is_account_flagged(driver) -> bool:
    """Check if the current page shows a checkpoint/ban warning."""
    url = driver.current_url.lower()
    page = driver.page_source.lower()

    if "checkpoint" in url or "disabled" in url:
        log.critical(f"Checkpoint URL: {url}")
        return True

    for indicator in CHECKPOINT_INDICATORS:
        if indicator in page:
            log.critical(f"Checkpoint detected: '{indicator}'")
            return True

    return False


# ===================================================================
# COOL-DOWN AFTER ERRORS
# ===================================================================
def cool_down(hours: float = 2.0) -> None:
    """Sleep for a long time to let the account cool down."""
    seconds = int(hours * 3600)
    log.warning(f"Cooling down for {hours}h ({seconds}s)")
    time.sleep(seconds)


# ===================================================================
# TEST
# ===================================================================
if __name__ == "__main__":
    log.info("Testing anti-detection driver...")
    driver = create_stealth_driver(headless=False)
    driver.get("https://bot.sannysoft.com")  # Bot detection test site
    human_delay(3, 5)
    print("Check the page - all tests should be green (not detected).")
    input("Press Enter to close...")
    driver.quit()
