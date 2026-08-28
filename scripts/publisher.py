"""Publish one approved slot to Instagram as a carousel.

The approval gate is the heart of this pipeline: a slot is published ONLY
when today's state has approvals[slot] is True (checked with `is True`, so
None/False/anything else never publishes). Do not weaken or remove it.

On cron the slot is derived from the ET hour (free 10:xx / food 12:xx /
gem 15:xx / art 18:xx / night 20:xx); firings at other ET hours (the
"wrong" DST twin) exit quietly.
--dry-run walks the whole flow (manifest, approval, Pages image checks) and
prints the Graph API calls it would make, without touching Telegram or IG.
"""
import argparse
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    MAX_HASHTAGS, SLOT_HOURS, SLOTS, env, graph_get, graph_post, image_url,
    load_manifest, load_state, now_et, save_state, tg_send, today_et,
)


def slot_from_time():
    hour = now_et().hour
    for slot, h in SLOT_HOURS.items():
        if hour == h:
            return slot
    return None


def run(slot, dry_run):
    date = today_et()
    manifest = load_manifest(date)
    if not manifest or slot not in manifest.get("slots", {}):
        print(f"no manifest entry for {date}/{slot}; nothing to do")
        return
    state = load_state(date)

    # approval gate — publish only on an explicit True. Do not change.
    if state["approvals"].get(slot) is not True:
        print(f"{slot} not approved (approvals[{slot}]={state['approvals'].get(slot)!r}); "
              "nothing published")
        return
    if slot in state.get("published", {}):
        print(f"{slot} already published today "
              f"({state['published'][slot].get('permalink', '')}); exiting")
        return

    info = manifest["slots"][slot]
    urls = [image_url(date, slot, f) for f in info["images"]]
    if not 2 <= len(urls) <= 10:
        raise RuntimeError(f"carousel needs 2-10 images, got {len(urls)}")
    for u in urls:  # Pages must serve every image before IG gets the URLs
        r = requests.get(u, timeout=30, stream=True)
        r.close()
        if r.status_code != 200:
            raise RuntimeError(f"image not reachable (HTTP {r.status_code}): {u}")

    hashtags = [t if t.startswith("#") else "#" + t for t in info.get("hashtags", [])]
    hashtags = hashtags[:MAX_HASHTAGS]  # IG rule of this account: 5 max, excess dropped
    caption = info.get("caption", "").strip()
    if hashtags:
        caption = f"{caption}\n\n{' '.join(hashtags)}".strip()
    caption = caption[:2200]

    ig_user = env("IG_USER_ID")
    if dry_run:
        for u in urls:
            print(f"[dry-run] graph POST /{ig_user}/media image_url={u} is_carousel_item=true")
        print(f"[dry-run] graph POST /{ig_user}/media media_type=CAROUSEL "
              f"children=<{len(urls)} ids> caption=<{len(caption)} chars>")
        print(f"[dry-run] graph POST /{ig_user}/media_publish creation_id=<carousel container>")
        print(f"[dry-run] {slot} would be published with {len(urls)} images")
        return

    children = []
    for u in urls:
        res = graph_post(f"{ig_user}/media", {"image_url": u, "is_carousel_item": "true"})
        children.append(res["id"])
        print(f"child container {len(children)}/{len(urls)} created")
    car_params = {
        "media_type": "CAROUSEL",
        "children": ",".join(children),
        "caption": caption,
    }
    # 위치 태그: 인스타 지도(Places)에서 발견되는 경로라 붙일 수 있으면 붙인다.
    # 캐러셀 컨테이너에 location_id 가 먹는지는 문서에 명시가 없어서, 실패하면
    # 위치 없이 한 번 더 시도한다. 게시 자체가 실패하면 안 되기 때문이다.
    loc = (info.get("location_id") or "").strip()
    if loc:
        try:
            car = graph_post(f"{ig_user}/media", {**car_params, "location_id": loc})
            print(f"carousel container created with location_id={loc}")
        except Exception as e:
            print(f"location_id={loc} 거부됨 ({e}); 위치 없이 재시도")
            car = graph_post(f"{ig_user}/media", car_params)
    else:
        car = graph_post(f"{ig_user}/media", car_params)
    creation_id = car["id"]
    for _ in range(36):  # carousel containers can take a couple minutes to process
        status = graph_get(creation_id, {"fields": "status_code"}).get("status_code", "")
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise RuntimeError("carousel container processing returned ERROR")
        time.sleep(5)
    pub = graph_post(f"{ig_user}/media_publish", {"creation_id": creation_id})
    media_id = pub["id"]
    permalink = graph_get(media_id, {"fields": "permalink"}).get("permalink", "")

    state.setdefault("published", {})[slot] = {
        "media_id": media_id,
        "permalink": permalink,
        "at": now_et().isoformat(timespec="seconds"),
    }
    save_state(date, state)
    tg_send(f"📤 {slot.upper()} 게시 완료\n{permalink}", ignore_errors=True)
    print(f"published {slot}: {permalink}")


def catchup():
    """승인됐고 슬롯 시각이 지났는데 아직 안 올라간 슬롯을 게시한다.

    GitHub Actions 의 cron 은 몇 시간씩 밀리거나 아예 발화하지 않는 날이 있다
    (2026-08-27: publish cron 이 하루 종일 한 번도 안 돌았다). 그래서 10분마다
    도는 approvals 워크플로가 이 함수를 호출해 밀린 슬롯을 따라잡는다.

    - 승인 게이트는 run() 이 그대로 지킨다 (approvals[slot] is True 일 때만)
    - 슬롯 시각(HH:30 ET) 전에는 절대 먼저 올리지 않는다
    - 한 번에 한 슬롯만 올린다. 밀린 게 여러 개여도 10분 간격으로 하나씩 나가서
      연속 게시가 Meta 의 스팸 감지에 걸리지 않는다
    - 실패한 슬롯은 state 의 failed 에 기록하고 그날은 다시 시도하지 않는다
      (Meta 차단 상황에서 10분마다 재시도해 차단을 키우는 것을 막는다)
    """
    date = today_et()
    manifest = load_manifest(date)
    if not manifest:
        print(f"no manifest for {date}; nothing to catch up")
        return
    state = load_state(date)
    n = now_et()
    published = state.get("published", {})
    failed = state.get("failed", {})

    def is_due(slot):
        h = SLOT_HOURS[slot]
        return n.hour > h or (n.hour == h and n.minute >= 30)

    due = [s for s in SLOTS
           if s in manifest.get("slots", {})
           and state["approvals"].get(s) is True
           and s not in published
           and s not in failed
           and is_due(s)]
    if not due:
        print(f"nothing due for catchup (ET {n:%H:%M})")
        return

    slot = due[0]
    print(f"catchup: {slot} 이 {SLOT_HOURS[slot]}:30 ET 부터 밀려 있음 - 지금 게시")
    try:
        run(slot, False)
    except Exception as e:  # error text is token-free by construction (common.py)
        state = load_state(date)
        state.setdefault("failed", {})[slot] = {
            "error": str(e)[:300],
            "at": now_et().isoformat(timespec="seconds"),
        }
        save_state(date, state)
        tg_send(f"❌ {slot.upper()} 자동 게시 실패 (오늘은 자동 재시도하지 않습니다)\n{e}",
                ignore_errors=True)
        print(f"catchup failed for {slot}: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", default="", help="free/food/gem/art/night (빈 값이면 ET 시각으로 결정)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--catchup", action="store_true",
                    help="승인됐는데 슬롯 시각이 지나도록 안 올라간 것을 하나 게시 (cron 지연 대비)")
    args = ap.parse_args()

    if args.catchup:
        catchup()  # 실패해도 워크플로를 빨갛게 만들지 않는다 (10분마다 도는 잡)
        return

    slot = args.slot.strip().lower() or slot_from_time()
    if slot not in SLOTS:
        print(f"no slot for this run (ET now {now_et():%H:%M}); exiting")
        return
    try:
        run(slot, args.dry_run)
    except Exception as e:  # error text is token-free by construction (common.py)
        if not args.dry_run:
            tg_send(f"❌ {slot.upper()} 게시 실패: {e}", ignore_errors=True)
        raise


if __name__ == "__main__":
    main()
