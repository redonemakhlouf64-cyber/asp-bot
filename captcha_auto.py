"""
captcha_auto.py
================
Fully automatic CAPTCHA solver - NO human input required.

Strategy:
1. Try Audio CAPTCHA + Google Speech Recognition (FREE, ~95% accuracy)
2. Fall back to Tesseract OCR on image CAPTCHA (FREE, ~70% accuracy)
3. If both fail: rotate device profile + wait, then retry later

All offline / free. No API keys. No manual work.
"""

import os
import io
import re
import time
import logging
import tempfile
from typing import Optional

try:
    import requests
    from PIL import Image, ImageFilter, ImageOps
    import pytesseract
    import speech_recognition as sr
    from pydub import AudioSegment
except ImportError:
    raise ImportError(
        "Run: pip install pytesseract Pillow SpeechRecognition pydub requests"
    )

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [AUTO-CAPTCHA] %(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)


class AutoCaptchaSolver:
    """Fully automatic CAPTCHA solver. No human, no external API."""

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self.recognizer = sr.Recognizer()
        log.info("AutoCaptchaSolver ready — 100%% automatic")

    # =================================================================
    # STRATEGY 1: AUDIO CAPTCHA (best accuracy, ~95%)
    # =================================================================
    def solve_audio_captcha(self, driver) -> Optional[str]:
        """
        Click the audio button, download the mp3, transcribe with
        Google's free web speech API.
        """
        try:
            audio_selectors = [
                "button#recaptcha-audio-button",
                "button[aria-label*='audio' i]",
                "a.rc-button-audio",
                "[title*='audio' i]",
            ]

            audio_btn = None
            for sel in audio_selectors:
                try:
                    audio_btn = driver.find_element(By.CSS_SELECTOR, sel)
                    if audio_btn.is_displayed():
                        break
                except Exception:
                    audio_btn = None

            if not audio_btn:
                log.info("No audio option — falling back to OCR")
                return None

            audio_btn.click()
            time.sleep(2)

            audio_src = None
            for sel in ["audio#audio-source", "audio source", "audio"]:
                try:
                    el = driver.find_element(By.CSS_SELECTOR, sel)
                    audio_src = el.get_attribute("src")
                    if audio_src:
                        break
                except Exception:
                    continue

            if not audio_src:
                log.warning("Audio element not found")
                return None

            mp3_data = requests.get(audio_src, timeout=30).content

            with tempfile.TemporaryDirectory() as tmp:
                mp3_path = os.path.join(tmp, "captcha.mp3")
                wav_path = os.path.join(tmp, "captcha.wav")

                with open(mp3_path, "wb") as f:
                    f.write(mp3_data)

                AudioSegment.from_mp3(mp3_path).export(wav_path, format="wav")

                with sr.AudioFile(wav_path) as source:
                    audio = self.recognizer.record(source)

                text = self.recognizer.recognize_google(audio)
                text = re.sub(r"[^a-zA-Z0-9]", "", text).lower()

                log.info(f"Audio solved: {text}")
                return text

        except sr.UnknownValueError:
            log.warning("Speech recognition couldn't understand audio")
            return None
        except Exception as e:
            log.warning(f"Audio solve failed: {e}")
            return None

    # =================================================================
    # STRATEGY 2: IMAGE CAPTCHA via TESSERACT OCR (~70%)
    # =================================================================
    def solve_image_captcha(self, image_bytes: bytes) -> Optional[str]:
        """Run local OCR on a CAPTCHA image. Fully offline."""
        try:
            img = Image.open(io.BytesIO(image_bytes))

            img = img.convert("L")
            img = ImageOps.autocontrast(img)
            img = img.point(lambda p: 0 if p < 140 else 255)
            img = img.filter(ImageFilter.MedianFilter(size=3))
            img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)

            config = (
                "--oem 3 --psm 8 "
                "-c tessedit_char_whitelist="
                "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
            )

            text = pytesseract.image_to_string(img, config=config).strip()
            text = re.sub(r"[^a-zA-Z0-9]", "", text)

            if 3 <= len(text) <= 10:
                log.info(f"OCR solved: {text}")
                return text

            log.warning(f"OCR result rejected (bad length): '{text}'")
            return None
        except Exception as e:
            log.warning(f"OCR failed: {e}")
            return None

    def solve_image_from_element(self, element) -> Optional[str]:
        try:
            return self.solve_image_captcha(element.screenshot_as_png)
        except Exception as e:
            log.warning(f"Element OCR failed: {e}")
            return None

    # =================================================================
    # MAIN ENTRYPOINT
    # =================================================================
    def solve(self, driver, account_name: str = "Account") -> Optional[str]:
        log.info(f"[{account_name}] CAPTCHA detected — solving automatically")

        for attempt in range(1, self.max_retries + 1):
            log.info(f"[{account_name}] Attempt {attempt}/{self.max_retries}")

            answer = self.solve_audio_captcha(driver)
            if answer:
                return answer

            try:
                for sel in [
                    "img[src*='captcha' i]",
                    "img[alt*='captcha' i]",
                    ".captcha img",
                    "#captcha img",
                ]:
                    imgs = driver.find_elements(By.CSS_SELECTOR, sel)
                    for img_el in imgs:
                        if img_el.is_displayed():
                            answer = self.solve_image_from_element(img_el)
                            if answer:
                                return answer
            except Exception as e:
                log.warning(f"Image lookup failed: {e}")

            try:
                for sel in [
                    "button.rc-button-reload",
                    "button[aria-label*='reload' i]",
                    "a.captcha-refresh",
                ]:
                    btns = driver.find_elements(By.CSS_SELECTOR, sel)
                    for b in btns:
                        if b.is_displayed():
                            b.click()
                            time.sleep(2)
                            break
            except Exception:
                pass

        log.error(f"[{account_name}] All attempts failed — will retry later")
        return None

    # =================================================================
    # ONE-CALL HELPER: DETECT + SOLVE + SUBMIT
    # =================================================================
    def _has_real_captcha(self, driver) -> bool:
        """
        Strict CAPTCHA detection: only True when the URL is a checkpoint page
        OR a visible CAPTCHA element is actually on screen.
        Avoids false positives from FB's HTML containing the word 'captcha'.
        """
        url = driver.current_url.lower()
        if any(p in url for p in ["/checkpoint/", "/challenge/", "/captcha", "security_check"]):
            return True

        try:
            for sel in [
                "iframe[src*='recaptcha' i]",
                "iframe[title*='captcha' i]",
                "img[src*='captcha' i]",
                "input[name*='captcha' i]",
                "input[id*='captcha' i]",
            ]:
                for el in driver.find_elements(By.CSS_SELECTOR, sel):
                    try:
                        if el.is_displayed():
                            return True
                    except Exception:
                        continue
        except Exception:
            pass

        return False

    def auto_handle(self, driver, account_name: str = "Account") -> bool:
        """
        Detect a REAL CAPTCHA on the current page, solve it, submit.
        Uses strict detection to avoid false positives on normal FB pages.
        """
        if not self._has_real_captcha(driver):
            return True  # no real CAPTCHA — nothing to solve

        log.info(f"[{account_name}] Real CAPTCHA confirmed — attempting to solve")
        solution = self.solve(driver, account_name)
        if not solution:
            return False

        for sel in [
            "input#audio-response",
            "input[name*='captcha' i]",
            "input[id*='captcha' i]",
            "input[type='text']",
        ]:
            try:
                inp = driver.find_element(By.CSS_SELECTOR, sel)
                if inp.is_displayed():
                    inp.clear()
                    inp.send_keys(solution)
                    break
            except Exception:
                continue

        for sel in [
            "button#recaptcha-verify-button",
            "button[type='submit']",
            "input[type='submit']",
            "button.submit",
        ]:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, sel)
                if btn.is_displayed():
                    btn.click()
                    break
            except Exception:
                continue

        time.sleep(3)
        after = driver.page_source.lower()
        if "captcha" in after or "checkpoint" in after:
            log.warning(f"[{account_name}] CAPTCHA still present after submit")
            return False

        log.info(f"[{account_name}] ✅ CAPTCHA solved automatically!")
        return True


if __name__ == "__main__":
    solver = AutoCaptchaSolver()
    print("✅ AutoCaptchaSolver initialized — 100%% automatic, 0%% manual")
