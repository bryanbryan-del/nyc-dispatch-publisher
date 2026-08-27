# nyc-dispatch-publisher

Instagram **@nycdispatch** 자동 게시 파이프라인. 아침 Cowork 예약 작업이 카드 내용
(spec.json)을 Drive에 올리면, GitHub Actions가 **카드 렌더링 → 텔레그램 미리보기 →
Bryan 승인 → 승인된 슬롯만 정해진 시각에 Instagram 캐러셀 게시**를 처리한다.
**승인 없으면 아무것도 나가지 않는다.**

## 1. 하루 흐름 (ET)

```
~7:00   Cowork 예약 작업: 이벤트 조사 → spec.json 을 Drive uploads/<날짜>/ 에 업로드
7:20/35 render.yml  → Drive에서 spec+build.py+render_cards.py 를 받아 카드 렌더링,
                      posts/<날짜>/ 커밋 → 커밋되면 preview 를 직접 발동
(즉시)  preview.yml → 텔레그램에 슬롯별 앨범 + 캡션 + ✅/⏭ 버튼 (하루 1회, 재발송은 수동 실행)
10분마다 approvals.yml → 버튼/글 승인을 수거해 state 기록, "승인 상태 변경 ✅" 확인 답장
10:30   publish.yml → free   (approvals[free] is True 일 때만)
12:30   publish.yml → food
15:30   publish.yml → gem
18:30   publish.yml → art
20:30   publish.yml → night
```

이미지는 GitHub Pages(main root)로 서빙: `https://bryanbryan-del.github.io/nyc-dispatch-publisher/posts/<날짜>/<slot>/01.jpg`
(URL에 `?rev=<commit>` 캐시버스터가 붙는다)

## 2. 파일 구성

| 경로 | 역할 |
|---|---|
| `.github/workflows/render.yml` | Drive의 spec.json으로 카드 렌더링 → posts/ 커밋 → preview 발동. 실패 시 텔레그램 알림 |
| `.github/workflows/preview.yml` | 미리보기 발송. posts/ push·cron(7:50 ET 백업)·수동. `preview_sent` 플래그로 하루 1회 |
| `.github/workflows/approvals.yml` | 10분마다 승인 수거 + 변경 시 확인 답장 |
| `.github/workflows/publish.yml` | 슬롯 게시 cron (UTC 0,1,14-17,19,20,22,23시 30분 = 5슬롯 × EDT/EST) |
| `.github/workflows/ingest.yml` | (fallback) Drive에 완성 이미지가 올라온 날짜를 반입. manifest가 이미 있으면 스킵 |
| `.github/workflows/selftest.yml` | 시크릿/텔레그램/Instagram/Pages 연결 자가진단 (수동) |
| `scripts/common.py` | SLOTS·SLOT_HOURS·ET 시간·state·텔레그램/Graph 헬퍼 (토큰 노출 없는 에러) |
| `scripts/preview.py` / `approvals.py` / `publisher.py` | 각 워크플로 본체 |
| `scripts/ingest.py` / `upload.py` | fallback 반입 / (구버전) 직접 업로드 |
| `posts/<날짜>/` | `<slot>/01.jpg...` + `manifest.json` |
| `state/<날짜>.json` | approvals·published·preview_sent 플래그. `state/telegram.json`=getUpdates offset (지우지 말 것) |

## 3. 스키마

`posts/<날짜>/manifest.json` (render.yml이 spec으로부터 생성):

```json
{
  "date": "2026-08-27",
  "slots": {
    "free": {
      "title": "이벤트명",
      "caption": "영어 캡션 (해시태그 제외, 첫 1-2줄 훅)",
      "hashtags": ["#nyc", "...최대 5개"],
      "images": ["01.jpg", "..."],
      "location_id": "선택: 인스타 위치 태그 id(숫자)"
    },
    "food": {}, "gem": {}, "art": {}, "night": {}
  }
}
```

- 슬롯은 free/food/gem/art/night 5개. 없는 슬롯은 그냥 건너뛴다.
- 해시태그 세트당 최대 5개(초과분은 publisher가 자름), 캐러셀 2~10장, 캡션 2,200자 제한.

`state/<날짜>.json` (ET 날짜):

```json
{
  "approvals": { "free": true, "food": null, "gem": false, "art": null, "night": null },
  "published": { "free": { "media_id": "...", "permalink": "...", "at": "..." } },
  "preview_sent": true
}
```

- `approvals`: `true`=승인, `false`=건너뛰기, `null`=대기. **`is True`일 때만 게시** (변경 금지).

## 4. 시간과 DST

cron은 UTC로 EDT/EST 두 오프셋을 모두 등록하고, 스크립트가 `America/New_York`
현재 시각으로 자기 슬롯이 아니면 조용히 종료한다. **cron을 바꾸지 말 것.**
Actions cron은 5~30분 지연될 수 있으며, 미리보기는 push 발동이라 지연과 무관하다.

## 5. 텔레그램 승인

- 버튼 `✅ <SLOT> 승인` / `⏭ 건너뛰기`, 또는 글 명령 `ok all` / `ok free` / `ok 1 3` / `skip food`
  (1=free 2=food 3=gem 4=art 5=night, 오늘 세트에 적용)
- 승인은 10분 주기 approvals 워크플로가 수거하며, 반영되면 **"승인 상태 변경: ✅ FREE" 확인
  메시지가 온다.** 이 메시지가 곧 "잘 눌렸다"는 증거다.
- 등록된 `TELEGRAM_CHAT_ID` 외의 채팅은 전부 무시 (변경 금지).

## 6. 수동 실행

```bash
gh workflow run selftest.yml
gh workflow run render.yml -f force=true        # 오늘 카드 다시 렌더링
gh workflow run preview.yml                     # 미리보기 재발송 (수동은 플래그 무시)
gh workflow run approvals.yml                   # 승인 즉시 수거
gh workflow run publish.yml -f slot=free -f dry_run=true
gh workflow run publish.yml -f slot=free        # 슬롯 시각을 놓쳤을 때 수동 게시
```

같은 날 재게시: `state/<날짜>.json`의 `published`에서 slot 삭제 후 publish 수동 실행.

## 7. 문제 해결

| 증상 | 원인 | 조치 |
|---|---|---|
| 렌더링 실패 텔레그램 알림 | spec.json 카드에 when/where/cost 등 키 누락이 대부분 | Drive의 spec.json 확인 후 `render.yml -f force=true` |
| 미리보기가 안 옴 | render 미실행/실패 (경고 메시지는 하루 1회 옴) | Actions에서 render 로그 확인 → force 재실행 |
| 승인 확인 답장이 안 옴 | approvals 수거 전(최대 10분) 또는 다른 채팅에서 누름 | 10분 기다려도 없으면 `gh workflow run approvals.yml` |
| `not approved ... nothing published` | 승인 안 함(정상) | 승인 후 수동 게시 |
| `API access blocked (code 200)` | Meta 계정/앱 임시 제한 | developers.facebook.com 계정 확인 완료 후 재시도, 반복 호출 금지 |
| `image not reachable (HTTP 404)` | Pages 배포 전/파일명 불일치 | 1-2분 후 재시도, manifest images와 파일 비교 |
| graph 190 에러 | 토큰 만료 | System User 토큰 재발급 → `IG_ACCESS_TOKEN` 갱신 |
| 같은 update 중복 반영 | offset 유실 | `state/telegram.json` 지우지 말 것 |
| state가 초기화됨 | 웹 업로드로 state/ 덮어씀 | 웹에서 파일 올릴 때 state/는 건드리지 않기 |

## 8. 불변 규칙

- publisher의 승인 검사(`approvals[slot] is True`), 텔레그램 chat id 검사, cron은 바꾸지 않는다.
- Drive `uploads/` 폴더는 본인 + 서비스 계정(읽기)만 공유 유지 — render가 이 폴더의
  build.py를 실행하므로 쓰기 권한 공유는 코드 주입 통로가 된다.
- 토큰·시크릿 값은 출력·커밋·로그 금지.
