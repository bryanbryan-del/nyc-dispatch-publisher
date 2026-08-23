"""Connectivity self-test: secrets presence, Telegram, Instagram Graph, Pages.

Prints one ✅/❌ line per check, sends the same summary to Telegram, and
exits 1 if anything failed. Secret values themselves are never printed.
"""
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import env, graph_get, pages_base, tg, tg_send  # noqa: E402

REQUIRED = ("IG_ACCESS_TOKEN", "IG_USER_ID", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")


def check_secrets():
    missing = [n for n in REQUIRED if not os.environ.get(n, "").strip()]
    if missing:
        raise RuntimeError(f"missing: {', '.join(missing)}")
    return f"{len(REQUIRED)}/{len(REQUIRED)} present"


def check_telegram():
    me = tg("getMe", {})
    return "@" + me.get("username", "?")


def check_instagram():
    info = graph_get(env("IG_USER_ID"), {"fields": "username"})
    return "@" + info.get("username", "?")


def check_pages():
    url = f"{pages_base()}/README.md"
    r = requests.get(url, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} for {url} "
                           "(첫 배포 후 1-2분 걸림; Settings→Pages가 main/root인지 확인)")
    return url


def main():
    checks = [
        ("secrets", check_secrets),
        ("telegram bot", check_telegram),
        ("instagram graph", check_instagram),
        ("github pages", check_pages),
    ]
    lines, failed = [], False
    for name, fn in checks:
        try:
            detail = fn()
            lines.append(f"✅ {name} — {detail}")
        except Exception as e:
            lines.append(f"❌ {name} — {e}")
            failed = True
    report = "\n".join(lines)
    print(report)
    try:
        tg_send("🔧 selftest 결과\n" + report)
    except Exception as e:
        print(f"warning: could not send summary to telegram: {e}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
