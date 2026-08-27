"""Send today's card sets to Telegram as albums with approval buttons.

실행 경로는 세 가지다:
  - push: render/수동 커밋으로 posts/ 가 바뀌면 즉시 발송 (지연과 무관하게 카드를 따라감)
  - cron(11:50/12:50 UTC): push 를 놓친 날의 백업
  - workflow_dispatch: 수동 재발송 (항상 발송)

시간 창 검사는 쓰지 않는다 - cron 지연으로 창을 벗어나면 미리보기가 조용히
누락되는 사고가 있었다(2026-08-25). 대신 state 의 preview_sent 플래그로
하루 1회만 발송하고, 수동 실행만 플래그를 무시하고 재발송한다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    MAX_HASHTAGS, SLOTS, env, image_url, load_manifest, load_state,
    save_state, tg, tg_send, today_et,
)

SLOT_LABELS = {"free": "🆓 FREE (1)", "food": "🌮 FOOD (2)", "gem": "💎 GEM (3)",
               "art": "🎨 ART (4)", "night": "🌙 NIGHT (5)"}


def main():
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    manual = event == "workflow_dispatch"
    date = today_et()
    manifest = load_manifest(date)
    state = load_state(date)

    if not manifest:
        # 경고는 하루 1회만 (cron 이 EDT/EST 두 번 발화해도 중복 경고 없음)
        if manual or not state.get("preview_warned"):
            tg_send(f"⚠️ {date} manifest.json이 repo에 없습니다. 아침 카드 렌더링이 실행됐는지 확인해 주세요.")
            state["preview_warned"] = True
            save_state(date, state)
        print(f"no manifest for {date}")
        return

    if state.get("preview_sent") and not manual:
        print(f"preview already sent for {date}; skipping ({event})")
        return

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
                f"{SLOT_LABELS.get(slot, slot.upper())} — {info.get('title', '')}".strip(" —"),
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

    state["preview_sent"] = True
    save_state(date, state)  # 오늘 state 파일 생성 + 발송 플래그
    tg_send(
        "미리보기 끝. 버튼을 누르거나 글로 승인하세요: "
        "`ok all` / `ok free` / `ok 1 3` / `skip food`\n"
        "승인은 10분 안에 '승인 상태 변경' 확인 메시지로 답장됩니다.",
        parse_mode="Markdown",
    )
    print(f"preview sent for {date}: {sent} slot(s) ({event})")


if __name__ == "__main__":
    main()
