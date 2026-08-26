"""Send today's card sets to Telegram as albums with approval buttons.

The cron fires at 11:50 and 12:50 UTC; only the firing that lands inside the
7:30-8:15 ET window proceeds (the other exits quietly), so exactly one
preview goes out per day regardless of DST. Manual dispatch always runs.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    MAX_HASHTAGS, SLOTS, env, image_url, load_manifest, load_state, now_et,
    save_state, tg, tg_send, today_et,
)

SLOT_LABELS = {"free": "🆓 FREE (1)", "food": "🌮 FOOD (2)", "gem": "💎 GEM (3)",
               "art": "🎨 ART (4)", "night": "🌙 NIGHT (5)"}


def in_window():
    n = now_et()
    return (n.hour == 7 and n.minute >= 30) or (n.hour == 8 and n.minute <= 15)


def main():
    manual = os.environ.get("GITHUB_EVENT_NAME", "") == "workflow_dispatch"
    if not manual and not in_window():
        print(f"outside ET preview window (ET now {now_et():%H:%M}); exiting")
        return
    date = today_et()
    manifest = load_manifest(date)
    if not manifest:
        tg_send(f"⚠️ {date} manifest.json이 repo에 없습니다. 아침 카드 업로드가 실행됐는지 확인해 주세요.")
        print(f"no manifest for {date}")
        return

    state = load_state(date)
    sent = 0
    for slot in SLOTS:
        info = manifest.get("slots", {}).get(slot)
        if not info:
            continue
        media = [{"type": "photo", "media": image_url(date, slot, f)} for f in info["images"][:10]]
        tg("sendMediaGroup", {"chat_id": env("TELEGRAM_CHAT_ID"), "media": media})
        hashtags = " ".join(info.get("hashtags", [])[:MAX_HASHTAGS])
        text = "\n\n".join(
            part for part in (
                f"{SLOT_LABELS[slot]} — {info.get('title', '')}".strip(" —"),
                info.get("caption", "").strip(),
                hashtags,
            ) if part
        )
        buttons = {"inline_keyboard": [[
            {"text": f"✅ {slot.upper()} 승인", "callback_data": f"ok:{slot}"},
            {"text": f"⏭ {slot.upper()} 건너뛰기", "callback_data": f"skip:{slot}"},
        ]]}
        tg_send(text[:4000], reply_markup=buttons)
        sent += 1

    save_state(date, state)  # ensures today's state file exists with pending approvals
    tg_send(
        "미리보기 끝. 버튼을 누르거나 글로 승인하세요: "
        "`ok all` / `ok free` / `ok 1 3` / `skip food`",
        parse_mode="Markdown",
    )
    print(f"preview sent for {date}: {sent} slot(s)")


if __name__ == "__main__":
    main()
