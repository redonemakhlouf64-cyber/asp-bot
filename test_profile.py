"""
test_profile.py — Direct HTTP post (no browser, no Selenium).
Uses requests library + cookies to POST to Facebook's mbasic endpoint.
This bypasses ALL browser detection.
"""
import json
import re
import sys
import logging
from pathlib import Path
import requests

COOKIES_DIR = Path("cookies")
SCREENSHOTS_DIR = Path("screenshots")
SCREENSHOTS_DIR.mkdir(exist_ok=True)
POST_FILE = Path("post.txt")
POST_TEXT = POST_FILE.read_text(encoding="utf-8").strip() if POST_FILE.exists() else "🧪 اختبار"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [DIRECT] %(levelname)s: %(message)s")
log = logging.getLogger("direct")


def cookies_to_dict(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return {c["name"]: c["value"] for c in data}


def save_html(name: str, content: str):
    p = SCREENSHOTS_DIR / f"direct_{name}.html"
    try:
        p.write_text(content[:50000], encoding="utf-8")
        log.info(f"📄 Saved: {p.name}")
    except Exception as e:
        log.warning(f"Save failed: {e}")


def main():
    files = sorted(COOKIES_DIR.glob("*.json"))
    if not files:
        log.error("❌ No cookies")
        sys.exit(1)

    log.info("=" * 50)
    log.info("🌐 DIRECT HTTP POST TEST (no browser)")
    log.info(f"Cookies: {files[0].name}")
    log.info(f"Message: {POST_TEXT[:60]}")
    log.info("=" * 50)

    cookies = cookies_to_dict(files[0])
    log.info(f"🍪 Loaded {len(cookies)} cookies")

    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
                      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5,ar;q=0.3",
    })

    # 1. Load home page to get fb_dtsg token + form
    log.info("🌐 GET https://mbasic.facebook.com/")
    r = session.get("https://mbasic.facebook.com/", timeout=30, allow_redirects=True)
    log.info(f"   Status: {r.status_code}")
    log.info(f"   Final URL: {r.url}")
    log.info(f"   Length: {len(r.text)} chars")
    save_html("1_home", r.text)

    if "/login" in r.url or "checkpoint" in r.url:
        log.error("❌ Redirected to login/checkpoint")
        log.error(f"→ URL: {r.url}")
        log.error("→ DIAGNOSIS: cookies invalid or account limited")
        sys.exit(1)

    if len(r.text) < 5000:
        log.warning(f"⚠️  Response very short ({len(r.text)} chars)")

    # Extract fb_dtsg token
    dtsg_patterns = [
        r'name="fb_dtsg" value="([^"]+)"',
        r'"DTSGInitialData",\[\],\{"token":"([^"]+)"',
        r'"token":"([^"]+)".*?fb_dtsg',
    ]
    fb_dtsg = None
    for pat in dtsg_patterns:
        m = re.search(pat, r.text)
        if m:
            fb_dtsg = m.group(1)
            log.info(f"✅ Got fb_dtsg via pattern: {pat[:40]}...")
            log.info(f"   Token: {fb_dtsg[:30]}...")
            break

    if not fb_dtsg:
        log.error("❌ Could NOT find fb_dtsg token in response")
        log.info("→ HTML dump saved to direct_1_home.html")
        log.info("→ This means FB is not serving the classic form")
        sys.exit(1)

    # Extract composer form action
    form_patterns = [
        r'<form[^>]+action="([^"]*composer[^"]*)"',
        r'<form[^>]+action="([^"]+)"[^>]*>[^<]*<textarea[^>]+name="xc_message"',
    ]
    composer_action = None
    for pat in form_patterns:
        m = re.search(pat, r.text, re.DOTALL)
        if m:
            composer_action = m.group(1).replace("&amp;", "&")
            log.info(f"✅ Found composer form action: {composer_action[:80]}")
            break

    if not composer_action:
        log.warning("⚠️  No composer form on home. Trying default paths...")
        composer_action = "/composer/mbasic/"

    if not composer_action.startswith("http"):
        composer_action = "https://mbasic.facebook.com" + composer_action

    # 2. POST the message
    post_data = {
        "fb_dtsg": fb_dtsg,
        "xc_message": POST_TEXT,
        "view_post": "Post",
    }

    log.info(f"📤 POST {composer_action}")
    r2 = session.post(composer_action, data=post_data, timeout=30, allow_redirects=True)
    log.info(f"   Status: {r2.status_code}")
    log.info(f"   Final URL: {r2.url}")
    log.info(f"   Response length: {len(r2.text)}")
    save_html("2_post_response", r2.text)

    # Check success indicators
    text_lower = r2.text.lower()
    if any(x in r2.url.lower() for x in ["/login", "checkpoint"]):
        log.error("❌ POST redirected to login/checkpoint")
        sys.exit(1)

    if "story_id" in text_lower or "story_fbid" in text_lower:
        log.info("✅✅✅ POST SUCCESS — story_id in response!")
    elif r2.url != composer_action and r2.status_code == 200:
        log.info("✅ Likely SUCCESS (redirected after POST)")
        log.info(f"   → Redirected to: {r2.url}")
    else:
        log.warning("⚠️  Unclear result — check direct_2_post_response.html")
        # Show first bit
        snippet = r2.text[:1500]
        for line in snippet.split("\n")[:30]:
            log.info(f"   {line}")

    log.info("=" * 50)
    log.info("🏁 Test complete — check artifacts for HTML dumps")
    log.info("=" * 50)


if __name__ == "__main__":
    main()
