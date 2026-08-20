#!/usr/bin/env python3
"""
add_account.py - v6.2
Auto-login FB accounts and save cookies as GitHub secrets.
"""
import os
import sys
import json
import time
import re
import imaplib
import email as email_lib
from base64 import b64encode
from urllib import request as urlreq
from urllib.error import HTTPError
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from nacl import encoding, public

API_BASE = "https://api.github.com/repos/"
FB_BASE = "https://www.facebook.com"

REPO = os.environ.get("GITHUB_REPOSITORY", "")
GH_PAT = os.environ.get("GH_PAT", "")
FB_ACCOUNTS_STR = os.environ.get("FB_ACCOUNTS", "")
GMAIL_EMAIL = os.environ.get("GMAIL_EMAIL", "")
GMAIL_APP_PW = os.environ.get("GMAIL_APP_PW", "")
ACCOUNT_NUM = os.environ.get("ACCOUNT_NUM", "").strip()
MANUAL_CODE = os.environ.get("MANUAL_CODE", "").strip()
FORCE_ALL = os.environ.get("FORCE_ALL", "false").lower() == "true"


def log(msg):
    print("[add_account] " + str(msg), flush=True)


def gh_request(method, path, data=None):
    url = API_BASE + REPO + path
    headers = {
        "Authorization": "token " + GH_PAT,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urlreq.Request(url, data=body, headers=headers, method=method)
    try:
        with urlreq.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw)
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")
        log("GitHub API error " + str(e.code) + ": " + raw)
        raise


def get_repo_public_key():
    return gh_request("GET", "/actions/secrets/public-key")


def encrypt_secret(public_key_b64, secret_value):
    pub = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    sealed = public.SealedBox(pub)
    encrypted = sealed.encrypt(secret_value.encode("utf-8"))
    return b64encode(encrypted).decode("utf-8")


def upsert_secret(name, value):
    pk = get_repo_public_key()
    encrypted = encrypt_secret(pk["key"], value)
    data = {"encrypted_value": encrypted, "key_id": pk["key_id"]}
    gh_request("PUT", "/actions/secrets/" + name, data=data)
    log("Secret " + name + " saved.")


def secret_exists(name):
    try:
        gh_request("GET", "/actions/secrets/" + name)
        return True
    except HTTPError as e:
        if e.code == 404:
            return False
        raise


def fetch_2fa_code(after_ts, timeout=180):
    if not GMAIL_EMAIL or not GMAIL_APP_PW:
        log("Gmail credentials missing.")
        return None
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            M = imaplib.IMAP4_SSL("imap.gmail.com")
            M.login(GMAIL_EMAIL, GMAIL_APP_PW)
            M.select("INBOX")
            typ, data = M.search(None, '(FROM "facebookmail.com")')
            if typ == "OK":
                ids = data[0].split()
                for msg_id in reversed(ids[-10:]):
                    typ, msg_data = M.fetch(msg_id, "(RFC822)")
                    if typ != "OK":
                        continue
                    raw = msg_data[0][1]
                    msg = email_lib.message_from_bytes(raw)
                    date_hdr = msg.get("Date", "")
                    try:
                        parsed = email_lib.utils.parsedate_tz(date_hdr)
                        date_ts = email_lib.utils.mktime_tz(parsed)
                    except Exception:
                        continue
                    if date_ts < after_ts - 10:
                        continue
                    body_text = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                try:
                                    body_text += part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                except Exception:
                                    pass
                    else:
                        try:
                            body_text = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                        except Exception:
                            body_text = ""
                    subject = msg.get("Subject", "")
                    combined = subject + " " + body_text
                    m = re.search(r"\b(\d{5,8})\b", combined)
                    if m:
                        code = m.group(1)
                        log("Got 2FA code: " + code)
                        try:
                            M.logout()
                        except Exception:
                            pass
                        return code
            try:
                M.logout()
            except Exception:
                pass
        except Exception as e:
            log("Gmail poll error: " + str(e))
        time.sleep(15)
    log("Gmail 2FA timeout.")
    return None


def parse_accounts(s):
    accounts = []
    s = s.strip()
    if not s:
        return accounts
    for line in re.split(r"[\n|;]+", s):
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"[:,\s]+", line, maxsplit=1)
        if len(parts) == 2:
            accounts.append((parts[0].strip(), parts[1].strip()))
    return accounts


def login_account(email_addr, password, account_num):
    log("Login attempt acc #" + str(account_num) + ": " + email_addr[:3] + "***")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = context.new_page()
        try:
            page.goto(FB_BASE + "/login/", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector('input[name="email"]', timeout=30000)
            page.fill('input[name="email"]', email_addr)
            page.fill('input[name="pass"]', password)
            login_ts = int(time.time())
            page.click('button[name="login"]')
            time.sleep(5)
            try:
                page.wait_for_selector('input[name="approvals_code"]', timeout=15000)
                log("2FA required.")
                code = MANUAL_CODE if MANUAL_CODE else fetch_2fa_code(login_ts, timeout=180)
                if not code:
                    log("No 2FA code available.")
                    context.close()
                    browser.close()
                    return None
                page.fill('input[name="approvals_code"]', code)
                try:
                    page.click('button[type="submit"]', timeout=10000)
                except PWTimeout:
                    page.keyboard.press("Enter")
                time.sleep(5)
                for _ in range(4):
                    try:
                        btn = page.query_selector('button[type="submit"]')
                        if btn:
                            btn.click()
                            time.sleep(3)
                        else:
                            break
                    except Exception:
                        break
            except PWTimeout:
                log("No 2FA prompt.")
            time.sleep(5)
            try:
                page.goto(FB_BASE + "/", wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            time.sleep(3)
            current_url = page.url
            if "login" in current_url or "checkpoint" in current_url:
                log("Login failed: " + current_url)
                context.close()
                browser.close()
                return None
            cookies = context.cookies()
            has_c_user = any(c.get("name") == "c_user" for c in cookies)
            if not has_c_user:
                log("Missing c_user cookie.")
                context.close()
                browser.close()
                return None
            log("Login OK acc #" + str(account_num))
            cookies_json = json.dumps(cookies)
            context.close()
            browser.close()
            return cookies_json
        except Exception as e:
            log("Playwright error: " + str(e))
            try:
                context.close()
                browser.close()
            except Exception:
                pass
            return None


def main():
    if not REPO or not GH_PAT:
        log("Missing GITHUB_REPOSITORY or GH_PAT.")
        sys.exit(1)
    accounts = parse_accounts(FB_ACCOUNTS_STR)
    if not accounts:
        log("No accounts in FB_ACCOUNTS.")
        sys.exit(1)
    log("Found " + str(len(accounts)) + " account(s).")
    if ACCOUNT_NUM:
        try:
            idx = int(ACCOUNT_NUM) - 1
            if idx < 0 or idx >= len(accounts):
                log("ACCOUNT_NUM out of range.")
                sys.exit(1)
            accounts_to_process = [(idx, accounts[idx])]
        except ValueError:
            log("Invalid ACCOUNT_NUM.")
            sys.exit(1)
    else:
        accounts_to_process = list(enumerate(accounts))
    processed = 0
    failed = 0
    skipped = 0
    for idx, (email_addr, password) in accounts_to_process:
        acc_num = idx + 1
        secret_name = "FB_COOKIES_" + str(acc_num)
        if not FORCE_ALL:
            try:
                if secret_exists(secret_name):
                    log("Acc #" + str(acc_num) + " already has cookies, skipping.")
                    skipped += 1
                    continue
            except Exception as e:
                log("Check error: " + str(e))
        cookies_json = login_account(email_addr, password, acc_num)
        if not cookies_json:
            log("Acc #" + str(acc_num) + " failed.")
            failed += 1
            continue
        try:
            upsert_secret(secret_name, cookies_json)
            processed += 1
        except Exception as e:
            log("Save failed acc #" + str(acc_num) + ": " + str(e))
            failed += 1
    log("Done. OK:" + str(processed) + " Skip:" + str(skipped) + " Fail:" + str(failed))
    if failed > 0 and processed == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
