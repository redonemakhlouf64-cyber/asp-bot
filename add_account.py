#!/usr/bin/env python3
"""Auto Login v6.2 - processes ALL new accounts in ONE run."""
import os, sys, json, time, imaplib, email, re, base64
import urllib.request
from playwright.sync_api import sync_playwright

REPO = os.environ.get("GITHUB_REPOSITORY", "").strip()
GH_PAT = os.environ.get("GH_PAT", "").strip()
FB_ACCOUNTS = os.environ.get("FB_ACCOUNTS", "").strip()
GMAIL_EMAIL = os.environ.get("GMAIL_EMAIL", "").strip()
GMAIL_APP_PW = os.environ.get("GMAIL_APP_PW", "").strip()
ACCOUNT_NUM = os.environ.get("ACCOUNT_NUM", "").strip()
MANUAL_CODE = os.environ.get("MANUAL_CODE", "").strip()
FORCE_ALL = os.environ.get("FORCE_ALL", "false").strip().lower() == "true"

def log(m):
    print(f"[add-account] {m}", flush=True)

def parse_accounts():
    accounts = []
    for i, line in enumerate(FB_ACCOUNTS.split("\n"), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        email_addr, pw = line.split(":", 1)
        accounts.append({
            "num": i,
            "email": email_addr.strip(),
            "password": pw.strip()
        })
    return accounts

def get_existing_cookies():
    if not GH_PAT or not REPO:
        return set()
    try:
        url = f"https://api.github.com/repos/{REPO}/actions/secrets?per_page=100"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {GH_PAT}",
            "Accept": "application/vnd.github+json"
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        existing = set()
        for s in data.get("secrets", []):
            m = re.match(r"^FB_COOKIES_(\d+)$", s["name"])
            if m:
                existing.add(int(m.group(1)))
        return existing
    except Exception as e:
        log(f"get_existing_cookies fail: {str(e)[:80]}")
        return set()

def get_public_key():
    url = f"https://api.github.com/repos/{REPO}/actions/secrets/public-key"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github+json"
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def encrypt_secret(public_key_b64, secret_value):
    from nacl import encoding, public
    pk = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    sealed = public.SealedBox(pk).encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(sealed).decode("utf-8")

def save_secret(name, value):
    pk_data = get_public_key()
    encrypted = encrypt_secret(pk_data["key"], value)
    url = f"https://api.github.com/repos/{REPO}/actions/secrets/{name}"
    body = json.dumps({
        "encrypted_value": encrypted,
        "key_id": pk_data["key_id"]
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="PUT", headers={
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json"
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status in (201, 204)

def fetch_code_from_gmail(timeout=180):
    log("waiting for FB code in Gmail...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            M = imaplib.IMAP4_SSL("imap.gmail.com")
            M.login(GMAIL_EMAIL, GMAIL_APP_PW)
            M.select("inbox")
            typ, data = M.search(None, '(FROM "facebook" UNSEEN)')
            ids = data[0].split()
            for i in reversed(ids[-5:]):
                typ, msg_data = M.fetch(i, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body += part.get_payload(decode=True).decode(errors="ignore")
                else:
                    body = msg.get_payload(decode=True).decode(errors="ignore")
                m = re.search(r"\b(\d{5,8})\b", body)
                if m:
                    M.store(i, "+FLAGS", "\\Seen")
                    M.close()
                    M.logout()
                    return m.group(1)
            M.close()
            M.logout()
        except Exception as e:
            log(f"imap error: {str(e)[:60]}")
        time.sleep(10)
    return None

def login_and_save(email_addr, password, num):
    log(f"login acc{num}: {email_addr}")
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            ctx = br.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768}
            )
            page = ctx.new_page()
            page.goto("https://www.facebook.com/login", timeout=45000)
            page.wait_for_timeout(4000)
            page.locator('input[name="email"]').fill(email_addr)
            page.locator('input[name="pass"]').fill(password)
            page.locator('button[name="login"]').click()
            page.wait_for_timeout(8000)
            if page.locator('input[name="approvals_code"]').count() > 0:
                log("2FA required")
                code = MANUAL_CODE if MANUAL_CODE else fetch_code_from_gmail()
                if not code:
                    log("no code found")
                    return False
                page.locator('input[name="approvals_code"]').fill(code)
                page.locator('button:has-text("Continue")').first.click()
                page.wait_for_timeout(6000)
                for _ in range(3):
                    try:
                        page.locator('button:has-text("Continue")').first.click(timeout=5000)
                        page.wait_for_timeout(4000)
                    except:
                        break
            page.wait_for_timeout(4000)
            if "login" in page.url or "checkpoint" in page.url:
                log(f"login failed - URL: {page.url}")
                return False
            cookies = ctx.cookies()
            cookies_json = json.dumps(cookies)
            ok = save_secret(f"FB_COOKIES_{num}", cookies_json)
            if ok:
                log(f"acc{num} saved to FB_COOKIES_{num}")
                return True
            return False
        finally:
            br.close()

def main():
    if not FB_ACCOUNTS or not GH_PAT or not REPO:
        log("missing FB_ACCOUNTS, GH_PAT, or REPO")
        sys.exit(1)
    accounts = parse_accounts()
    log(f"parsed {len(accounts)} accounts")
    if ACCOUNT_NUM:
        targets = [a for a in accounts if a["num"] == int(ACCOUNT_NUM)]
    elif FORCE_ALL:
        targets = accounts
    else:
        existing = get_existing_cookies()
        log(f"existing FB_COOKIES: {sorted(existing)}")
        targets = [a for a in accounts if a["num"] not in existing]
    log(f"will process {len(targets)} accounts")
    success = 0
    for a in targets:
        try:
            if login_and_save(a["email"], a["password"], a["num"]):
                success += 1
            time.sleep(30 + (a["num"] * 3))
        except Exception as e:
            log(f"acc{a['num']} error: {str(e)[:80]}")
    log(f"DONE - {success}/{len(targets)} success")

if __name__ == "__main__":
    main()
