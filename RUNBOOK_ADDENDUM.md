# RUNBOOK ADDENDUM — 아침 예약 작업과 게시 파이프라인의 연결 (v3)

> (구버전 안내) PAT로 GitHub에 직접 커밋하는 방식(v1)과 완성 이미지를 Drive에
> 올리는 방식(v2)은 폐기됐다. 클라우드 세션은 GitHub API가 차단되고 큰 이미지
> 업로드도 실패하기 때문이다. 현재 방식은 **텍스트 spec만 올리고 렌더링은
> GitHub Actions(render.yml)가 한다.**

## 현재 방식 (v3): spec.json 업로드

아침 예약 작업은 카드를 직접 만들지 않는다. 대신:

1. 이벤트 조사 후 **spec.json** (각 슬롯의 카피·사진·레이아웃 데이터)을
   Drive `uploads/<오늘 ET 날짜>/` 폴더에 업로드한다
   (uploads 폴더 id: `1sk0hwtIvXW7o8vK30noIgwjA1btSx0ql`).
2. 렌더링 코드 `build.py` / `render_cards.py` 는 uploads 폴더(또는 날짜 폴더)에
   있는 것을 render.yml이 받아서 실행한다.
3. render.yml(7:20/7:35 ET)이 spec으로 카드를 그려 `posts/<날짜>/`에 커밋하고
   미리보기를 발동한다. 이후 승인·게시는 자동.

## spec.json 필수 규칙 (render 실패의 최다 원인)

- **brief 카드마다 `when` / `where` / `cost` 키 필수.** 하나라도 빠지면 렌더링이
  KeyError로 실패하고 텔레그램으로 실패 알림이 간다 (2026-08-26 실사례).
- 슬롯 키는 free / food / gem / art / night. 캡션 영어, 해시태그 슬롯당 최대 5개,
  긴 대시(—) 금지.
- 업로드 후 Drive에서 spec.json이 실제로 생겼는지 조회로 검증하고,
  "uploaded spec for <날짜>" 를 결과 보고에 포함한다.
- 가능하면 7:15 ET 전에 업로드를 끝낸다 (render 첫 발화가 7:20).

## 파이프라인이 보장하는 것

- 미리보기는 카드 커밋 즉시 발송 (cron 지연과 무관)
- 승인 버튼/명령은 10분 주기로 수거되고, 반영되면 "승인 상태 변경 ✅" 확인 답장이 온다
- 게시(ET): free 10:30 / food 12:30 / gem 15:30 / art 18:30 / night 20:30 —
  승인된 슬롯만 나간다
