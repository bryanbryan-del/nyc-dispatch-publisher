"""Collect approval decisions from Telegram and record them in today's state.

Runs at the start of every publish workflow (and can be dispatched alone).
Reads getUpdates from the last stored offset (state/telegram.json), applies
button callbacks ("ok:free" / "skip:art") and text commands
("ok all" / "ok free" / "ok 1 3" / "skip food") to today's ET state file.

Only updates coming from TELEGRAM_CHAT_ID are honored. Never remove or
loosen that check — it is what keeps strangers from approving posts.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    ROOT, SLOTS, env, load_state, read_json, save_state, tg, tg_send,
    today_et, write_json,
)

NUM2SLOT = {"1": "free", "2": "food", "3": "art"}


def parse_command(text):
    """'ok all' | 'ok free' | 'ok 1 3' | 'skip food' -> (verb, [slots]) or None."""
    parts = (text or "").strip().lower().split()
    if not parts or parts[0] not in ("ok", "skip"):
        return None
    verb, args = parts[0], parts[1:] or ["all"]
    if "all" in args:
        return verb, list(SLOTS)
    slots = []
    for a in args:
        s = NUM2SLOT.get(a, a)
        if s in SLOTS and s not in slots:
            slots.append(s)
    return (verb, slots) if slots else None


def apply(state, verb, slots):
    for s in slots:
        state["approvals"][s] = (verb == "ok")
    mark = "✅" if verb == "ok" else "⏭"
    return [f"{mark} {s.upper()}" for s in slots]


def main():
    chat_id = env("TELEGRAM_CHAT_ID")
    tstate = read_json(ROOT / "state" / "telegram.json", {"offset": 0})
    updates = tg("getUpdates", {
        "offset": tstate.get("offset", 0),
        "timeout": 0,
        "allowed_updates": ["message", "callback_query"],
    }) or []

    date = today_et()
    state = load_state(date)
    changed = []
    for u in updates:
        tstate["offset"] = max(tstate.get("offset", 0), u["update_id"] + 1)
        cq = u.get("callback_query")
        if cq is not None:
            if str(cq.get("message", {}).get("chat", {}).get("id")) != str(chat_id):
                continue  # chat id check — never act on other chats
            verb, _, slot = (cq.get("data") or "").partition(":")
            if verb in ("ok", "skip") and slot in SLOTS:
                changed += apply(state, verb, [slot])
            tg("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "반영했습니다"},
               ignore_errors=True)
            continue
        msg = u.get("message")
        if msg is not None:
            if str(msg.get("chat", {}).get("id")) != str(chat_id):
                continue  # chat id check — never act on other chats
            cmd = parse_command(msg.get("text", ""))
            if cmd:
                changed += apply(state, *cmd)

    save_state(date, state)
    write_json(ROOT / "state" / "telegram.json", tstate)
    if changed:
        tg_send(f"{date} 승인 상태 변경: " + ", ".join(changed), ignore_errors=True)
    print(f"processed {len(updates)} update(s); changes: {', '.join(changed) or 'none'}")
    print(f"approvals now: {state['approvals']}")


if __name__ == "__main__":
    main()
