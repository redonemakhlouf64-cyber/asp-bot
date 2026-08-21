#!/usr/bin/env python3
"""
auto_doctor.py v1.0 — بوت الإصلاح الذاتي
- يقرأ لوج الـ workflow الفاشل
- يطابق الخطأ مع قاعدة معرفة
- يطبق الإصلاح تلقائياً
"""

import os
import re
import sys
import json
import subprocess
from pathlib import Path

LOG_FILE = os.environ.get("LOG_FILE", "failed_workflow.log")
WORKFLOW_NAME = os.environ.get("WORKFLOW_NAME", "unknown")

# 📚 قاعدة معرفة الأخطاء وإصلاحاتها
DIAGNOSTICS = [
    {
        "name": "libasound2_missing",
        "pattern": r"Package 'libasound2' has no installation candidate",
        "file": ".github/workflows/{workflow}.yml",
        "fix_type": "replace",
        "find": "runs-on: ubuntu-latest",
        "replace": "runs-on: ubuntu-22.04",
        "description": "Switched to ubuntu-22.04 (fixes libasound2)",
        "can_retry": True,
    },
    {
        "name": "content_empty",
        "pattern": r"CONTENT empty",
        "file": "content.txt",
        "fix_type": "create_if_missing",
        "content": "📚 مرحبا بكم! تابعونا للمزيد 🚀\n\n#تطوير_الذات",
        "description": "Created default content.txt",
        "can_retry": True,
    },
    {
        "name": "groups_zero",
        "pattern": r"Groups: 0",
        "file": None,
        "fix_type": "notify",
        "description": "groups.txt فارغ — شغّل Auto Joiner أولاً",
        "can_retry": False,
    },
    {
        "name": "session_expired",
        "pattern": r"(Session invalid|session_expired|Please log in)",
        "file": None,
        "fix_type": "notify",
        "description": "❌ الكوكيز انتهت — حدّث FB_COOKIES_1 secret يدوياً",
        "can_retry": False,
    },
    {
        "name": "checkpoint",
        "pattern": r"checkpoint",
        "file": None,
        "fix_type": "notify",
        "description": "🚨 تحقق أمان من فيسبوك — افتح الحساب يدوياً وحل التحقق",
        "can_retry": False,
    },
    {
        "name": "playwright_missing",
        "pattern": r"ModuleNotFoundError: No module named 'playwright'",
        "file": "requirements.txt",
        "fix_type": "append_if_missing",
        "content": "playwright==1.47.0",
        "description": "Added playwright to requirements.txt",
        "can_retry": True,
    },
    {
        "name": "chromium_install_failed",
        "pattern": r"Failed to install browsers",
        "file": ".github/workflows/{workflow}.yml",
        "fix_type": "replace",
        "find": "playwright install --with-deps chromium",
        "replace": "playwright install --with-deps chromium || playwright install chromium",
        "description": "Added Chromium install fallback",
        "can_retry": True,
    },
    {
        "name": "timeout_error",
        "pattern": r"(TimeoutError|Timeout \d+ms exceeded)",
        "file": None,
        "fix_type": "retry_only",
        "description": "⏱️ Timeout مؤقت — إعادة المحاولة",
        "can_retry": True,
    },
    {
        "name": "network_error",
        "pattern": r"(net::ERR_|Connection reset|ECONNRESET|ETIMEDOUT)",
        "file": None,
        "fix_type": "retry_only",
        "description": "🌐 خطأ شبكة مؤقت — إعادة المحاولة",
        "can_retry": True,
    },
    {
        "name": "all_groups_no_textarea",
        "pattern": r"no_textarea: (\d+)",
        "file": None,
        "fix_type": "notify",
        "description": "🧹 كل الجروبات تفشل — غالباً الحساب غير عضو. شغّل Auto Joiner",
        "can_retry": False,
    },
    {
        "name": "python_syntax",
        "pattern": r"SyntaxError: (.+) \(.+, line (\d+)\)",
        "file": None,
        "fix_type": "notify",
        "description": "❌ خطأ في كود Python — يحتاج تعديل يدوي",
        "can_retry": False,
    },
    {
        "name": "missing_secret",
        "pattern": r"FB_COOKIES_\d+ empty",
        "file": None,
        "fix_type": "notify",
        "description": "🔐 secret مفقود — أضف FB_COOKIES_1 من GitHub Settings",
        "can_retry": False,
    },
    {
        "name": "rate_limit",
        "pattern": r"(rate limit|too many requests|429)",
        "file": None,
        "fix_type": "retry_delayed",
        "description": "🚦 Rate limit من فيسبوك — انتظار 30 دقيقة",
        "can_retry": True,
    },
    {
        "name": "disk_space",
        "pattern": r"(No space left on device|ENOSPC)",
        "file": None,
        "fix_type": "retry_only",
        "description": "💾 القرص ممتلئ — يحدث أحياناً في runners",
        "can_retry": True,
    },
    {
        "name": "cookies_malformed",
        "pattern": r"(JSONDecodeError|Invalid cookies|cookie.*malformed)",
        "file": None,
        "fix_type": "notify",
        "description": "🔑 تنسيق الكوكيز خاطئ — راجع FB_COOKIES_1 secret",
        "can_retry": False,
    },
]

result = {
    "detected": [],
    "fixed": [],
    "failed_to_fix": [],
    "notifications": [],
    "can_retry": False,
}


def log(msg):
    print(f"[doctor] {msg}", flush=True)


def read_log():
    if not Path(LOG_FILE).exists():
        log(f"❌ Log file not found: {LOG_FILE}")
        return ""
    return Path(LOG_FILE).read_text(encoding="utf-8", errors="ignore")


def apply_fix(diag, log_content):
    """يطبق الإصلاح حسب نوعه"""
    name = diag["name"]
    fix_type = diag["fix_type"]
    log(f"🔧 Applying fix: {name} ({fix_type})")

    if fix_type == "notify":
        result["notifications"].append(diag["description"])
        return False  # لا يمكن الإصلاح تلقائياً

    if fix_type in ("retry_only", "retry_delayed"):
        result["notifications"].append(diag["description"])
        return True  # فقط أعد المحاولة

    file_path = diag["file"]
    if file_path and "{workflow}" in file_path:
        file_path = file_path.replace("{workflow}", WORKFLOW_NAME)

    if not file_path:
        return False

    fp = Path(file_path)

    if fix_type == "replace":
        if not fp.exists():
            log(f"  ⚠️ File not found: {fp}")
            return False
        content = fp.read_text(encoding="utf-8")
        find_str = diag["find"]
        replace_str = diag["replace"]
        if find_str not in content:
            log(f"  ℹ️ Pattern not found in {fp} (ربما مصلح مسبقاً)")
            return False
        new_content = content.replace(find_str, replace_str)
        fp.write_text(new_content, encoding="utf-8")
        log(f"  ✅ Fixed {fp}")
        result["fixed"].append(f"{fp}: {diag['description']}")
        return True

    if fix_type == "create_if_missing":
        if fp.exists() and fp.stat().st_size > 0:
            log(f"  ℹ️ {fp} already exists")
            return False
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(diag["content"], encoding="utf-8")
        log(f"  ✅ Created {fp}")
        result["fixed"].append(f"{fp}: {diag['description']}")
        return True

    if fix_type == "append_if_missing":
        line = diag["content"]
        existing = fp.read_text(encoding="utf-8") if fp.exists() else ""
        if line in existing:
            return False
        fp.write_text(existing.rstrip() + "\n" + line + "\n", encoding="utf-8")
        log(f"  ✅ Appended to {fp}")
        result["fixed"].append(f"{fp}: {diag['description']}")
        return True

    return False


def main():
    log("=" * 50)
    log("🩺 Auto-Doctor v1.0")
    log(f"Workflow: {WORKFLOW_NAME}")
    log("=" * 50)

    content = read_log()
    if not content:
        log("❌ No log to analyze")
        sys.exit(1)

    log(f"📄 Log size: {len(content)} chars")

    any_fixed = False
    for diag in DIAGNOSTICS:
        if re.search(diag["pattern"], content, re.IGNORECASE):
            log(f"🔍 Detected: {diag['name']}")
            result["detected"].append(diag["name"])
            fixed = apply_fix(diag, content)
            if fixed:
                any_fixed = True
                if diag["can_retry"]:
                    result["can_retry"] = True

    log("=" * 50)
    log(f"🔍 Detected: {len(result['detected'])} issue(s)")
    log(f"✅ Fixed:    {len(result['fixed'])}")
    log(f"💬 Notify:   {len(result['notifications'])}")
    log(f"🔄 Can retry: {result['can_retry']}")

    if result["detected"]:
        log("\n📋 التفاصيل:")
        for f in result["fixed"]:
            log(f"  ✅ {f}")
        for n in result["notifications"]:
            log(f"  💬 {n}")

    # حفظ النتيجة ليستخدمها GitHub Actions
    Path("doctor_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))

    # GitHub Actions outputs
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"can_retry={str(result['can_retry']).lower()}\n")
            f.write(f"fixed_count={len(result['fixed'])}\n")
            f.write(f"detected_count={len(result['detected'])}\n")

    log("🎉 Diagnosis complete.")


if __name__ == "__main__":
    main()
