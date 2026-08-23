# nyc-dispatch-publisher

Instagram **@nycdispatch** 자동 게시 파이프라인. 아침 카드 제작(Cowork 스케줄 작업)이
`posts/<날짜>/`를 커밋하면, GitHub Actions가 **텔레그램 미리보기 → Bryan 버튼 승인 →
승인된 슬롯만 8:30 / 12:30 / 18:30 ET에 Instagram Graph API로 캐러셀 게시**를 처리한다.
**승인 없으면 아무것도 나가지 않는다.**

## 1. 흐름

```
07:00 ET  Cowork 아침 작업이 카드 6장 x 3세트 제작 → scripts/upload.py로 posts/<날짜>/ 커밋
07:50 ET  preview.yml   → 텔레그램에 앨범 3개 + 캡션 + ✅/⏭ 버튼
   ~      Bryan이 버튼 또는 글(`ok all` 등)로 승인
08:30 ET  publish.yml   → approvals 수집 → free 슬롯 approvals[free] is True면 게시
12:30 ET  publish.yml   → food
18:30 ET  publish.yml   → art
```

이미지는 GitHub Pages(main 브랜치 root)로 서빙된다:
`https://bryanbryan-del.github.io/nyc-dispatch-publisher/posts/<날짜>/<slot>/01.jpg`

## 2. 파일 구성

| 경로 | 역할 |
|---|---|
| `.github/workflows/preview.yml` | 아침 미리보기 (cron 11:50/12:50 UTC, ET 창은 스크립트가 판단) |
| `.github/workflows/publish.yml` | 슬롯 게시 (cron 12:30/13:30/16:30/17:30/22:30/23:30 UTC) |
| `.github/workflows/selftest.yml` | 연결 자가진단 (수동 실행) |
| `scripts/common.py` | 공용: ET 시간, 상태 파일, 텔레그램/Graph API 헬퍼 (토큰 노출 없는 에러) |
| `scripts/preview.py` | 앨범 + 캡션 + 승인 버튼 발송, 오늘 state 파일 생성 |
| `scripts/approvals.py` | 텔레그램 getUpdates 폴링 → 버튼/글 명령을 오늘 state에 반영 |
| `scripts/publisher.py` | **approvals[slot] is True일 때만** 캐러셀 게시. `--dry-run` 지원 |
| `scripts/selftest.py` | 시크릿/텔레그램/Instagram/Pages 점검 (✅/❌) |
| `scripts/upload.py` | 아침 작업이 카드+manifest를 커밋할 때 쓰는 독립 실행 스크립트 |
| `posts/` | `posts/<날짜>/<slot>/NN.jpg` + `posts/<날짜>/manifest.json` |
| `state/` | `state/<날짜>.json`(승인·게시 기록), `state/telegram.json`(getUpdates offset) |
| `RUNBOOK_ADDENDUM.md` | 아침 Cowork 작업 프롬프트에 붙일 업로드 문단 |

## 3. 스키마

`posts/<날짜>/manifest.json`:

```json
{
  "date": "2026-08-23",
  "slots": {
    "free": {
      "title": "Summer Streets Festival",
      "caption": "영어 캡션 본문 (해시태그 제외)",
      "hashtags": ["#nyc", "#nycevents", "#thingstodoinnyc", "#summerstreets", "#free"],
      "images": ["01.jpg", "02.jpg", "03.jpg", "04.jpg", "05.jpg", "06.jpg"]
    },
    "food": { "...": "동일 구조" },
    "art":  { "...": "동일 구조" }
  }
}
```

- 해시태그는 **세트당 5개 이하** (초과분은 publisher가 자른다).
- 이미지는 JPEG만(upload.py가 변환), 8MB 이하, 4:5.
- 캐러셀은 2~10장 (평소 6장).

`state/<날짜>.json` (날짜는 ET 기준):

```json
{
  "approvals": { "free": true, "food": null, "art": false },
  "published": {
    "free": { "media_id": "…", "permalink": "https://www.instagram.com/p/…", "at": "2026-08-23T08:31:02-04:00" }
  }
}
```

- `approvals`: `true`=승인, `false`=건너뛰기, `null`=대기. **`is True`일 때만 게시.**
- `state/telegram.json`: `{"offset": <마지막 update_id+1>}` — 지우지 말 것.

## 4. 시간과 DST

cron은 UTC이므로 EDT/EST 두 오프셋을 모두 등록해 두고, 각 스크립트가
`America/New_York` 현재 시각으로 자기 창(preview: 7:30–8:15 ET, publish: 8/12/18시 ET)이
아니면 조용히 종료한다. **cron을 바꾸지 말 것.** Actions cron은 5~15분 늦을 수 있다.

## 5. 텔레그램 승인

- 버튼: 미리보기 메시지의 `✅ <SLOT> 승인` / `⏭ <SLOT> 건너뛰기`
- 글 명령: `ok all` / `ok free` / `ok 1 3` / `skip food` (1=free, 2=food, 3=art, 오늘 세트에 적용)
- 승인 수집은 게시 워크플로 시작 시점(approvals.py)에 반영된다. 등록된
  `TELEGRAM_CHAT_ID` 외의 채팅에서 온 업데이트는 전부 무시한다(변경 금지).

## 6. 수동 실행

```bash
gh workflow run selftest.yml
gh workflow run preview.yml
gh workflow run publish.yml -f slot=free -f dry_run=true   # 흐름만 검증
gh workflow run publish.yml -f slot=free                   # 실제 게시 (주의)
```

같은 날 재게시: `state/<날짜>.json`의 `published`에서 해당 slot을 지우고 커밋한 뒤
`gh workflow run publish.yml -f slot=<slot>`.

## 7. 아침 업로드 (upload.py)

아침 작업(Cowork)은 repo를 clone하지 않고 `scripts/upload.py` 한 파일만 받아서 실행한다.
Fine-grained PAT(`GH_TOKEN`, 이 repo Contents: Read/write만)으로 git data API를 호출해
`posts/<날짜>/`를 한 커밋으로 올린다. 사용법은 `RUNBOOK_ADDENDUM.md` 참고.
성공 시 출력: `committed <n> files for <날짜> -> <sha>`.

## 8. 문제 해결

| 증상 | 원인 | 조치 |
|---|---|---|
| selftest ❌ telegram | 봇 토큰 오류/봇 차단 | `TELEGRAM_BOT_TOKEN` Secret 재확인, 봇과의 채팅에서 /start |
| selftest ❌ instagram graph | 토큰 만료·권한, Page-IG 연결 끊김 | System User 토큰 재발급 후 `IG_ACCESS_TOKEN` 업데이트; Page↔Instagram 연결 확인 |
| selftest ❌ github pages | Pages 미배포/설정 변경 | Settings→Pages가 `main`/root인지 확인, 1~2분 후 재시도 |
| 미리보기가 안 옴 | manifest 없음 / cron 지연 | `posts/<오늘>/manifest.json` 존재 확인, `gh run list --workflow preview.yml` |
| 앨범 이미지가 안 뜸 | Pages 배포 전(커밋 직후) | 1~2분 뒤 `curl -sI <이미지 URL>`이 200인지 확인 후 preview 재실행 |
| `not approved ... nothing published` | 승인 안 함(정상 동작) | 버튼/`ok <slot>` 후 재실행 |
| `image not reachable (HTTP 404)` | Pages 미배포 또는 파일명 불일치 | manifest `images`와 실제 파일명 비교, Pages 배포 대기 |
| 게시 중 `graph POST ... failed` | 토큰/권한/미디어 형식 | 에러 메시지의 code 확인; 190=토큰 재발급, 형식이면 JPEG·8MB·4:5 확인 |
| `carousel container processing ERROR` | 이미지 다운로드 실패/형식 | 이미지 URL 200 확인, JPEG 변환 여부 확인 |
| upload.py `HTTP 401/403` | GH_TOKEN 만료·권한 부족 | Fine-grained 토큰 재발급 (이 repo, Contents RW) |
| 같은 update가 중복 반영 | offset 유실 | `state/telegram.json`을 지우지 말 것 (남겨두면 자동 복구) |

## 9. 불변 규칙

- 워크플로 cron, publisher의 승인 검사(`approvals[slot] is True`), 텔레그램 chat id 검사는 바꾸지 않는다.
- 실제 게시는 Bryan의 명시적 OK 이후에만 수동 실행한다 (cron 게시는 승인 게이트가 지킨다).
- 토큰·시크릿 값은 출력·커밋·로그·인용 금지.
