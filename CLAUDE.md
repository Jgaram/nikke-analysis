# CLAUDE.md

간결하게 유지한다. 설명은 docs 에, 여기엔 규칙만.

## 브랜치

- `main` 하나만 쓴다. 세션 브랜치(`claude/` · `ccr-`)에 push 하면 `merge-to-main` 워크플로가 main 에 합쳐 테스트하고,
  통과하면 올린 뒤 세션 브랜치를 지운다. PR · 새 브랜치는 만들지 않는다.
- push 전에 `pip install -e ".[dev]"` (한 번) · `python -m pytest -q`. main 에 `refresh` 의 데이터 커밋이 계속 쌓이니
  `git fetch origin main && git merge origin/main` 으로 따라잡는다.
- push 뒤 `merge-to-main` 결과를 확인한다. 실패하면 main 은 그대로다 — 위 명령으로 합쳐 고치고 다시 push.

## 티어 사이트 (`web/`)

- `web/js/model.js` 는 `analyze/metrics.py` · `tiers.py` · `meta.py` 를 브라우저로 옮긴 것이다. 한쪽 계산을 고치면 다른 쪽도.
  `tests/test_web.py` 가 같은 인자에서 두 쪽이 같은지 본다(node 필요).
- 화면: `nikke build raids` 한 번, 그다음 `nikke web --serve`.

## 역할(딜러·서포터)은 모른다

랭킹엔 덱 대미지만 있고 니케별 딜량이 없다. 덱 대미지로 딜과 버프를 나누는 모형도 갈리지 않았다(lifecycle.md).

- 결과를 딜러·서포터로 해석하지 않는다. 가설로도 적지 않는다. 속성 시즌에만 쓰여도 딜러가 아니고(그 속성만 버프하는
  니케도 그렇다), 범용도·생애 곡선은 쓰임의 모양이지 역할이 아니다.
- 클래스(화력형·지원형·방어형)로 나눈 결과도 적지 않는다. 역할로 읽힌다.
- 니케별 딜량 자료가 생기기 전엔 손대지 않는다. 생기면 "자기 딜의 비중" 같은 연속 값으로 잰다.

## 티어

- 속성·종합 티어는 일부 시즌(옛 것, 최근 것, 아무거나)을 빼고 다시 계산해도 비슷해야 한다. 모형을 바꿀 땐 이걸로 잰다
  (time-review.md 6절, `docs/time-review/8_removal.py`).
- 체급은 덱 대미지 배수다 — 니케 자기 딜 배수(그 하한)로 적지 않는다. 티어에는 덱 몫 나누기(θ¹)에만 쓴다. 더 세게 나누면
  자기 몫, 곧 역할이 된다(power.md, metrics.md 1절).
