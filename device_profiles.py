"""
device_profiles.py
===================
Assigns each Facebook account a persistent, realistic device profile.
Account A always appears as iPhone 14, Account B as Windows laptop, etc.
Makes Facebook believe multiple real users from real devices.
"""

import os
import json
import random
import hashlib
import logging
from typing import Optional
from pathlib import Path

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
except ImportError:
    raise ImportError("Run: pip install selenium")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DEVICE] %(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)


# ===================================================================
# DEVICE PROFILES DATABASE
# ===================================================================
DEVICE_PROFILES = [
    # --- Windows 10/11 ---
    {
        "name": "Windows 11 - Chrome",
        "platform": "Win32",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "viewport": (1920, 1080),
        "device_scale": 1,
        "mobile": False,
        "touch": False,
        "languages": ["en-US", "en"],
        "timezone": "America/New_York",
        "webgl_vendor": "Google Inc. (Intel)",
        "webgl_renderer": "ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "hardware_concurrency": 8,
        "device_memory": 8,
    },
    {
        "name": "Windows 10 - Firefox",
        "platform": "Win32",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "viewport": (1366, 768),
        "device_scale": 1,
        "mobile": False,
        "touch": False,
        "languages": ["en-US", "en"],
        "timezone": "America/Chicago",
        "webgl_vendor": "Mozilla",
        "webgl_renderer": "Mozilla",
        "hardware_concurrency": 4,
        "device_memory": 8,
    },
    {
        "name": "Windows 11 - Edge",
        "platform": "Win32",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
        "viewport": (1536, 864),
        "device_scale": 1.25,
        "mobile": False,
        "touch": False,
        "languages": ["en-GB", "en"],
        "timezone": "Europe/London",
        "webgl_vendor": "Google Inc. (NVIDIA)",
        "webgl_renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "hardware_concurrency": 16,
        "device_memory": 16,
    },

    # --- macOS ---
    {
        "name": "MacBook Pro - Chrome",
        "platform": "MacIntel",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "viewport": (1440, 900),
        "device_scale": 2,
        "mobile": False,
        "touch": False,
        "languages": ["en-US", "en"],
        "timezone": "America/Los_Angeles",
        "webgl_vendor": "Google Inc. (Apple)",
        "webgl_renderer": "ANGLE (Apple, Apple M2 Pro, OpenGL 4.1)",
        "hardware_concurrency": 10,
        "device_memory": 16,
    },
    {
        "name": "MacBook Air - Safari",
        "platform": "MacIntel",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "viewport": (1280, 800),
        "device_scale": 2,
        "mobile": False,
        "touch": False,
        "languages": ["en-US", "en"],
        "timezone": "America/Denver",
        "webgl_vendor": "Apple Inc.",
        "webgl_renderer": "Apple M1",
        "hardware_concurrency": 8,
        "device_memory": 8,
    },

    # --- iPhone ---
    {
        "name": "iPhone 14 Pro - Safari",
        "platform": "iPhone",
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
        "viewport": (390, 844),
        "device_scale": 3,
        "mobile": True,
        "touch": True,
        "languages": ["en-US", "en"],
        "timezone": "America/New_York",
        "webgl_vendor": "Apple Inc.",
        "webgl_renderer": "Apple GPU",
        "hardware_concurrency": 6,
        "device_memory": 6,
    },
    {
        "name": "iPhone 13 - Safari",
        "platform": "iPhone",
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "viewport": (390, 844),
        "device_scale": 3,
        "mobile": True,
        "touch": True,
        "languages": ["en-GB", "en"],
        "timezone": "Europe/London",
        "webgl_vendor": "Apple Inc.",
        "webgl_renderer": "Apple GPU",
        "hardware_concurrency": 6,
        "device_memory": 4,
    },

    # --- Android ---
    {
        "name": "Samsung Galaxy S23 - Chrome",
        "platform": "Linux armv8l",
        "user_agent": "Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
        "viewport": (360, 780),
        "device_scale": 3,
        "mobile": True,
        "touch": True,
        "languages": ["en-US", "en"],
        "timezone": "America/Chicago",
        "webgl_vendor": "Qualcomm",
        "webgl_renderer": "Adreno (TM) 740",
        "hardware_concurrency": 8,
        "device_memory": 8,
    },
    {
        "name": "Google Pixel 8 - Chrome",
        "platform": "Linux armv8l",
        "user_agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
        "viewport": (412, 915),
        "device_scale": 2.625,
        "mobile": True,
        "touch": True,
        "languages": ["en-US", "en"],
        "timezone": "America/Los_Angeles",
        "webgl_vendor": "Google Inc.",
        "webgl_renderer": "ANGLE (Google, Vulkan 1.3.0 (Mali-G715 s",
        "hardware_concurrency": 9,
        "device_memory": 8,
    },

    # --- iPad ---
    {
        "name": "iPad Pro - Safari",
        "platform": "iPad",
        "user_agent": "Mozilla/5.0 (iPad; CPU OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
        "viewport": (1024, 1366),
        "device_scale": 2,
        "mobile": True,
        "touch": True,
        "languages": ["en-US", "en"],
        "timezone": "America/New_York",
        "webgl_vendor": "Apple Inc.",
        "webgl_renderer": "Apple GPU",
        "hardware_concurrency": 8,
        "device_memory": 8,
    },
]


# ===================================================================
# DEVICE PROFILE MANAGER
# ===================================================================
class DeviceProfileManager:
    """Assigns and remembers device profile per account."""

    def __init__(self, storage_dir: str = "state/devices"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_profile_file(self, account_id: str) -> Path:
        safe_id = hashlib.md5(account_id.encode()).hexdigest()[:16]
        return self.storage_dir / f"{safe_id}.json"

    def get_profile(self, account_id: str) -> dict:
        profile_file = self._get_profile_file(account_id)

        if profile_file.exists():
            try:
                with open(profile_file, "r", encoding="utf-8") as f:
                    profile = json.load(f)
                log.info(f"[{account_id}] Loaded: {profile['name']}")
                return profile
            except Exception as e:
                log.warning(f"Failed to load profile: {e}")

        hash_int = int(hashlib.md5(account_id.encode()).hexdigest(), 16)
        profile = DEVICE_PROFILES[hash_int % len(DEVICE_PROFILES)].copy()

        with open(profile_file, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)

        log.info(f"[{account_id}] Assigned NEW: {profile['name']}")
        return profile

    def list_profiles(self) -> None:
        for f in self.storage_dir.glob("*.json"):
            try:
                with open(f, "r") as file:
                    p = json.load(file)
                print(f"  {f.stem} -> {p['name']}")
            except Exception:
                pass

    def reset_profile(self, account_id: str) -> None:
        f = self._get_profile_file(account_id)
        if f.exists():
            f.unlink()
            log.info(f"[{account_id}] Profile reset")


# ===================================================================
# BUILD CHROME DRIVER FROM PROFILE
# ===================================================================
def create_driver_with_profile(
    profile: dict,
    headless: bool = True,
    session_dir: Optional[str] = None,
) -> webdriver.Chrome:
    options = Options()

    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-notifications")

    options.add_argument(f"--user-agent={profile['user_agent']}")

    w, h = profile["viewport"]
    options.add_argument(f"--window-size={w},{h}")

    lang_str = ",".join(profile["languages"])
    options.add_argument(f"--lang={profile['languages'][0]}")
    options.add_experimental_option("prefs", {
        "intl.accept_languages": lang_str,
        "profile.default_content_setting_values.notifications": 2,
    })

    if profile["mobile"]:
        mobile_emulation = {
            "deviceMetrics": {
                "width": w,
                "height": h,
                "pixelRatio": profile["device_scale"],
                "touch": profile["touch"],
            },
            "userAgent": profile["user_agent"],
        }
        options.add_experimental_option("mobileEmulation", mobile_emulation)

    if headless:
        options.add_argument("--headless=new")

    if session_dir:
        Path(session_dir).mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={os.path.abspath(session_dir)}")

    driver = webdriver.Chrome(options=options)

    _inject_fingerprint(driver, profile)

    try:
        driver.execute_cdp_cmd(
            "Emulation.setTimezoneOverride",
            {"timezoneId": profile["timezone"]},
        )
    except Exception:
        pass

    log.info(f"Driver ready: {profile['name']}")
    return driver


def _inject_fingerprint(driver, profile: dict) -> None:
    lang_json = json.dumps(profile["languages"])

    script = f"""
    Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
    Object.defineProperty(navigator, 'platform', {{ get: () => '{profile["platform"]}' }});
    Object.defineProperty(navigator, 'languages', {{ get: () => {lang_json} }});
    Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {profile["hardware_concurrency"]} }});
    Object.defineProperty(navigator, 'deviceMemory', {{ get: () => {profile["device_memory"]} }});
    Object.defineProperty(navigator, 'maxTouchPoints', {{ get: () => {5 if profile["touch"] else 0} }});

    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {{
        if (parameter === 37445) return '{profile["webgl_vendor"]}';
        if (parameter === 37446) return '{profile["webgl_renderer"]}';
        return getParameter.call(this, parameter);
    }};

    window.chrome = {{ runtime: {{}} }};
    """

    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": script},
        )
    except Exception as e:
        log.warning(f"Fingerprint injection: {e}")


def get_driver_for_account(
    account_id: str,
    headless: bool = True,
    session_base: str = "state/sessions",
) -> webdriver.Chrome:
    manager = DeviceProfileManager()
    profile = manager.get_profile(account_id)
    session_dir = f"{session_base}/{account_id}"
    return create_driver_with_profile(profile, headless, session_dir)


if __name__ == "__main__":
    manager = DeviceProfileManager()
    test_accounts = ["john_2025", "sarah_marketing", "mike_biz", "lisa_ecom", "tom_agency"]
    print("\n=== Device assignments ===")
    for acc in test_accounts:
        p = manager.get_profile(acc)
        print(f"  {acc:20s} -> {p['name']}")
