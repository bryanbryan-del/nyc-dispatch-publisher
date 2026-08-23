# RUNBOOK ADDENDUM — 아침 카드 작업의 repo 업로드

## (A) 배경

아침 Cowork 스케줄 작업(7:00 ET)이 만든 카드가 이 repo의 `posts/<날짜>/`에 올라와야
미리보기(7:50 ET)와 게시(8:30/12:30/18:30 ET)가 동작한다. 업로드는 repo clone 없이
`scripts/upload.py` 한 파일로 한다. 산출물 요구사항:

- 하루 폴더 하나: `free/`, `food/`, `art/` 세 하위 폴더 + `manifest.json`
- 슬롯당 이미지 6장(2~10장 허용), 4:5, PNG여도 됨(업로드 시 JPEG 변환·8MB 제한 적용)
- `manifest.json` 스키마는 repo `README.md` 3번 참고
  (date, slots.<slot>.title/caption/hashtags(≤5)/images)

## (B) Cowork 스케줄 작업 프롬프트에 붙일 문단

> 카드 세트 3개(free/food/art)를 완성하면 게시 파이프라인에 업로드한다:
> 하루 작업 폴더(예: `~/work/day`) 아래 `free/`, `food/`, `art/`에 각 세트의 카드
> 이미지를 순서대로 넣고, `manifest.json`을
> `https://raw.githubusercontent.com/bryanbryan-del/nyc-dispatch-publisher/main/README.md`
> 의 3번 스키마대로 작성한다(캡션은 영어, 해시태그는 세트당 5개 이하, date는 오늘 ET
> 날짜). 그 다음 실행:
>
> ```
> curl -sL -o upload.py https://raw.githubusercontent.com/bryanbryan-del/nyc-dispatch-publisher/main/scripts/upload.py
> pip install requests Pillow --quiet 2>/dev/null || pip install requests Pillow --break-system-packages --quiet
> export GH_REPO=bryanbryan-del/nyc-dispatch-publisher
> export GH_TOKEN=<토큰>
> python3 upload.py --dir ~/work/day
> ```
>
> `committed N files for <날짜> -> <sha>` 가 출력되면 성공. 이 출력 줄을 결과 보고에
> 포함한다. GH_TOKEN 값은 어디에도 출력·기록하지 않는다. 업로드가 실패하면 에러
> 메시지만 보고하고 재시도는 1회만 한다.

`<토큰>` 자리에는 Fine-grained PAT(이 repo 전용, Contents: Read/write)를 넣는다.
토큰은 이 프롬프트 외 어디에도 적지 않는다.
