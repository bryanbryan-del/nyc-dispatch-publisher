"""Shared helpers for the NYC Dispatch publishing pipeline.

All scheduling decisions are made in America/New_York (ET). Workflow crons
fire in UTC at both possible offsets (EST/EDT) and each script checks the ET
clock to decide whether the firing is "its" window, so DST needs no cron edit.

Secrets come from environment variables and must never be printed or logged.
Error messages raised here are deliberately token-free.
"""
import json
import os
import sys
import time  # noqa: F401  (used by scripts importing * for retry loops)
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ET = ZoneInfo("America/New_York")
SLOTS = ("free", "food", "gem", "art", "night")
SLOT_HOURS = {"free": 10, "food": 12, "gem": 15, "art": 18, "night": 20}  # ET publish hours (minute 30)
MAX_HASHTAGS = 5
GRAPH = "https://graph.facebook.com/v22.0"

ROOT = Path(__file__).resolve().parent.parent


def env(name, required=True):
    v = os.environ.get(name, "").strip()
    if required and not v:
        print(f"missing required env: {name}")
        sys.exit(1)
    return v


def now_et():
    return datetime.now(ET)


def today_et():
    return now_et().strftime("%Y-%m-%d")


def pages_base():
    override = os.environ.get("PAGES_BASE", "").strip()
    if override:
        return override.rstrip("/")
    repo_full = os.environ.get("GITHUB_REPOSITORY", "bryanbryan-del/nyc-dispatch-publisher")
    owner, _, repo = repo_full.partition("/")
    return f"https://{owner}.github.io/{repo}"


def image_url(date, slot, filename):
    # rev 쿼리로 텔레그램/CDN 캐시를 무효화한다 (같은 경로에 다른 이미지가
    # 커밋되면 텔레그램이 옛 캐시를 재사용하는 문제 방지).
    rev = os.environ.get("GITHUB_SHA", "")[:8]
    suffix = f"?rev={rev}" if rev else ""
    return f"{pages_base()}/posts/{date}/{slot}/{filename}{suffix}"


# ---------------------------------------------------------------- json/state

def read_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def state_path(date):
    return ROOT / "state" / f"{date}.json"


def load_state(date):
    return read_json(state_path(date), {"approvals": {s: None for s in SLOTS}, "published": {}})


def save_state(date, state):
    write_json(state_path(date), state)


def manifest_path(date):
    return ROOT / "posts" / date / "manifest.json"


def load_manifest(date):
    return read_json(manifest_path(date))


# ------------------------------------------------------------------ telegram

def tg(method, payload, ignore_errors=False):
    """Call the Telegram Bot API. Failures raise token-free RuntimeErrors."""
    token = env("TELEGRAM_BOT_TOKEN")
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=payload, timeout=60)
    except requests.RequestException as e:
        if ignore_errors:
            print(f"warning: telegram {method} network error: {type(e).__name__}")
            return None
        raise RuntimeError(f"telegram {method} network error: {type(e).__name__}") from None
    try:
        body = r.json()
    except ValueError:
        body = {}
    if not body.get("ok"):
        desc = body.get("description", f"HTTP {r.status_code}")
        if ignore_errors:
            print(f"warning: telegram {method} failed: {desc}")
            return None
        raise RuntimeError(f"telegram {method} failed: {desc}")
    return body["result"]


def tg_send(text, ignore_errors=False, **kw):
    payload = {"chat_id": env("TELEGRAM_CHAT_ID"), "text": text, "disable_web_page_preview": True}
    payload.update(kw)
    return tg("sendMessage", payload, ignore_errors=ignore_errors)


# ----------------------------------------------------------- instagram graph

def _graph_body(r, what):
    try:
        body = r.json()
    except ValueError:
        raise RuntimeError(f"{what} returned non-JSON (HTTP {r.status_code})") from None
    if "error" in body:
        err = body["error"]
        raise RuntimeError(
            f"{what} failed: {err.get('message', '')} (code {err.get('code', '?')})"
        )
    return body


def graph_post(path, payload):
    payload = dict(payload)
    payload["access_token"] = env("IG_ACCESS_TOKEN")
    what = f"graph POST /{path}"
    try:
        r = requests.post(f"{GRAPH}/{path}", data=payload, timeout=120)
    except requests.RequestException as e:
        raise RuntimeError(f"{what} network error: {type(e).__name__}") from None
    return _graph_body(r, what)


def graph_get(path, params):
    params = dict(params)
    params["access_token"] = env("IG_ACCESS_TOKEN")
    what = f"graph GET /{path}"
    try:
        r = requests.get(f"{GRAPH}/{path}", params=params, timeout=60)
    except requests.RequestException as e:
        raise RuntimeError(f"{what} network error: {type(e).__name__}") from None
    return _graph_body(r, what)
