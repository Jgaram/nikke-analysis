# nikke-analysis

승리의 여신: 니케의 **메타·티어 변화**를 패치 단위로 추적하는 파이프라인.
솔로레이드 상위 랭킹 데이터를 지표화해서 "지금 뭐가 강한가"가 아니라
**"무엇이, 언제, 왜 바뀌었는가"** 를 답하는 것이 목표.

지표보다 먼저 필요한 것이 **시간축**이다. "2주년 당시 메타"를 분석하려면 그때
어떤 솔로 레이드가 열려 있었고, 어떤 니케가 존재했는지를 먼저 정확히 알아야 한다.
그래서 지금 단계는 공지를 자동으로 모아 **시점별 니케 풀과 솔로 레이드 일정**을
복원하는 데 집중한다.

핵심 제약 하나: **런타임에 AI를 쓰지 않는다.** 새 패치, 새 니케, 새 시즌, 시즌
중단·재오픈은 사람이 읽고 판단해서가 아니라 `nikke refresh` 한 번으로 반영된다.

---

## 지금 상태

| 단계 | 상태 |
|---|---|
| 공지 수집 (공식 사이트 + 네이버 라운지) | ✅ 1,070건 (2022-06 ~), 새 공지·수정된 공지만 증분 수집 |
| 로스터 (니케 202명, EN/KO/JA 이름, 속성) | ✅ 게임 파일 + nikke-utils + enikk, 신캐는 다음 갱신 때 자동 추가 |
| 캐릭터별 출시일 | ✅ 공지 기반 134명 · 런칭 로스터 62명 · 데이터 파일 날짜 6명 |
| 솔로 레이드 달력 | ✅ 시즌 1–41 실제 운영 구간 (연기·중단·재오픈·연장 반영), enikk와 교차검증 |
| 시점 조회 `nikke asof` | ✅ 시즌 상태, 니케 풀, 진행 중 모집, 공지됐지만 미출시 니케 |
| enikk 랭킹 수집 | ⏸ 보류 — API(GraphQL)는 확인됨, 지표 단계에서 연결 |
| 지표·티어 엔진, 시각화 | ⏸ 보류 — 합성 데이터로 검증된 상태 유지 |
| CI 자동 갱신 | ✅ 주 2회 (`.github/workflows/refresh.yml`) |

`data/processed/` 의 표들은 실제로 생성된 데이터다. 테스트 109개.

---

## 빠른 시작

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

nikke asof 2주년           # 2024-11-04 정오(KST) 기준 게임 상태
nikke asof 2025-06-22      # 아무 날짜나, 2025-06-22T09:00 처럼 시각까지도
nikke seasons              # 솔로 레이드 전 시즌 일람
nikke refresh              # 수집 → 빌드, 의존 순서대로 전부
nikke check                # 사람이 봐야 할 게 있는지 (있으면 종료 코드 1)
pytest -q
```

### 시점 조회

```
$ nikke asof 2주년
2024-11-04 12:00 KST 기준 · 글로벌 출시 +731일

솔로 레이드
  현재 시즌 19 · Behemoth · 보스 수냉(Water) / 약점 전격(Electric) · 일시 중단 중
    운영 구간  2024-10-31 12:00 ~ 11/01 22:00 (중단)
               11/08 12:00 ~ 11/12 18:00 (중단)
               11/13 12:00 ~ 11/17 05:00 (연장)
    처음 공지된 일정  2024-10-31 12:00 ~ 11/07 04:59 (이후 변경)
    챌린지 기록 초기화 있음
  직전 시즌 18 · Land Eater · 보스 작열(Fire) / 약점 수냉(Water) · 종료
  다음 시즌 20 · White Ice Dragon · 보스 수냉(Water) / 약점 전격(Electric) · 오픈 예정

니케 풀  137명 (SSR 113 · SR 15 · R 9)
  속성별  작열 30 · 수냉 28 · 풍압 24 · 철갑 27 · ▶전격 28   (▶ = 솔로 레이드 약점 속성)
  최근 30일 출시  팬텀 (10/10) · 루마니 (10/17) · 라푼젤 : 퓨어 그레이스 (10/31) · 신데렐라 (10/31)
  공지됐지만 미출시  그레이브 (11/07 05:00)
  ...
```

`--units` 는 그 시점의 니케 전체 목록, `--json` 은 기계가 읽는 형식이다.
분석 코드에서는 같은 것을 파이썬으로 쓴다:

```python
from nikke_analysis.timeline import Timeline

timeline = Timeline.load()
view = timeline.at("2주년")
view.season.number, view.season.status_at(view.moment)   # (19, "suspended")
[u.unit_id for u in view.units]                          # 그때 존재한 니케
timeline.season(26).periods                              # 26시즌이 실제로 열려 있던 구간들
```

개별 단계:

```bash
nikke collect roster            # 게임 파일 + nikke-utils
nikke collect notices           # 공식 공지 + 네이버 라운지 (새 것/수정된 것만)
nikke collect enikk-meta        # enikk 시즌 메타·수집 시계열·캐릭터 표
nikke build timeline            # → roster, unit_releases, banners, soloraid_*, season_calendar
nikke status                    # 지금 디스크에 뭐가 있는지
```

> **네트워크**: 공식 공지 CMS, 네이버 라운지 API, enikk 에 닿아야 한다. 환경별 설정은
> [docs/network-policy.md](docs/network-policy.md).

---

## 무인 운영: 코드 한 줄, AI 없음

```bash
nikke refresh        # 또는 python -m nikke_analysis refresh
```

이 한 줄이 공지·로스터·enikk 를 새로 받고 모든 표를 다시 만든다. 공지 해석은 전부
고정 규칙(정규식)이고 런타임에 AI·LLM 호출은 없다. 같은 입력이면 결과가 바이트
단위로 같다. GitHub Actions 가 주 2회(월·목) 이 명령을 돌려 결과를 커밋하므로,
평소에는 아무것도 실행하지 않아도 `git pull` 만 하면 최신이다.

규칙은 공지가 **지금까지의 형식**을 유지하는 동안 맞는다 (2022 런칭 ~ 현재까지 유지됨).
형식이 바뀌면 규칙은 추측하지 않고 그 항목을 빼 두며, 그 사실을 `nikke check` 가
알려준다. 사람이 할 일은 그때 규칙이나 별칭을 한 번 고치는 것뿐이다.

| 점검 | 수준 | 예 |
|---|---|---|
| 수집 실패 (API 변경·장애) | 오류 | 공식 공지 API 가 404 |
| enikk 는 플레이를 봤는데 공지에서 일정을 못 찾은 시즌 | 오류 | 솔로 레이드 공지 문구가 바뀜 |
| 45일 넘게 새 업데이트 공지 없음 / 60일 넘게 새 시즌 없음 | 오류 | 수집이 조용히 멈춤 |
| 시즌 번호 충돌 | 오류 | 두 일정이 같은 시즌으로 묶임 |
| 공지에서 못 푼 니케 이름 | 경고 | 새 콜라보의 표기 → 다음 게임 파일 갱신 때 자동 해소되거나 별칭 1줄 추가 |
| 공지 기반 출시일이 없는 니케 | 경고 | 지금은 알려진 6명 |
| enikk 와 일정·속성 불일치 | 경고 | 공지되지 않은 연장? |

오류가 있으면 `nikke refresh` 와 `nikke check` 가 종료 코드 1로 끝나고, CI 는 받은
데이터를 커밋한 뒤 실패로 표시한다(GitHub 이 메일로 알린다). 결과 목록은
`data/processed/timeline_issues.csv` 와 Actions 실행 요약에 남는다.

---

## 구조

단계가 한 방향으로만 흐른다. 각 단계의 입력은 항상 **디스크 위의 파일**이고,
같은 입력이면 같은 출력이 나온다.

```
collect/     네트워크 → data/raw/          가져오기만 한다. 해석하지 않는다.
build/       raw      → data/processed/    순수 파싱·조인 (공지 해석, 달력 복원)
timeline.py  processed → 시점 조회          nikke asof / nikke seasons
analyze/     processed → metrics_*.csv     순수 계산 (보류)
viz/         metrics  → reports/*.png      렌더링 (보류)
```

`collect` 가 아무것도 해석하지 않는 게 중요한 이유:

- 사이트 마크업은 예고 없이 바뀐다. 파서가 깨져도 **이미 받아둔 스냅샷**으로
  고쳐서 다시 돌리면 된다.
- 공지는 수정되거나 내려갈 수 있다. 출시일과 시즌 일정의 근거가 공지이므로
  **공지 스냅샷은 커밋한다** (`data/raw/notices_*`). 수집은 증분이라 새 공지와
  수정된 공지만 쌓인다. 솔로레이드 랭킹(`enikk_soloraid`)과 enikk 시즌 메타
  (`enikk_seasons`)도 같은 이유로 커밋한다.
- 파서가 `bytes → records` 순수 함수가 되어 네트워크 없이 테스트된다.

### 데이터 흐름

```
   게임 파일 (ID·EN/KO/JA 이름·풀네임) ─┐
   nikke-utils (속성·데이터 등재일) ─────┼→ 로스터(이름) ─→ 별칭 표
   enikk /characters (속성 보충) ────────┘                    │
                                                              ▼
   공식 사이트 공지 ───┐                              출시일·모집 기간
                       ├→ 공지 표 ─────────────────→ (unit_releases, banners)
   네이버 라운지 공지 ─┘      │                                │
                              │                                ▼
                              └→ 솔로 레이드 이벤트 ──→ 시즌·운영 구간 ←─ enikk 수집 시계열
                                 (오픈·중단·재오픈·연장·연기)      (교차검증, 번호 매기기)
                                                                   │
                                                  로스터(출시일) ──┴─→ nikke asof
```

로스터를 **두 번** 빌드한다. 공지에서 니케 이름을 찾으려면 로스터가 만든 별칭
표가 필요하고, 로스터의 출시일은 그 공지에서 온다. 순환 의존 대신 싼 패스를 두 번.

---

## 출시일은 어떻게 정하나

**그 니케가 처음 소개된 업데이트 공지의 모집 시작 시각**이다. 공지 게시일도,
점검일도 아니다. 한 패치의 두 번째 신캐는 보통 일주일 뒤에 열린다:

```
1.2 SSR 니케 [신 : 스위프트 바니]
*특수 모집 기간: 2026년 9월 24일 5:00:00 ~ 2026년 10월 15일 4:59:59 (UTC+9)
```

재모집(선택 모집, 재합류)은 모집 기간 표(`banners.csv`)에는 남지만 출시일이 되지
않는다. 모집 없이 이벤트·로그인·해방 보상으로 들어온 니케(킬로, 라이, 니힐리스타…)는
그 업데이트 날짜를 쓴다. 근거가 약한 순서로:

| 출처 | 신뢰도 | 인원 | 의미 |
|---|---|---|---|
| `patchnote` | high | 134 | 공지의 모집 시작 시각 |
| `launch` | medium | 62 | 어떤 공지도 소개한 적 없고 출시 전부터 게임 데이터에 있던 니케 |
| `datafile` | low | 6 | 공지 원문이 없음 (2022-12-08 공지 누락 3명, 해방 시스템 3명) |

이름이 어긋나면 날짜가 엉뚱한 니케에 붙으므로 **추측하지 않는다.** 공지는 콜라보
니케를 풀네임으로 부르는데("스즈하라 사쿠라"), 이 풀네임은 게임 파일의 설명문에서
자동으로 별칭이 된다. 두 니케가 같은 이름을 쓰는 경우(사쿠라 2명)는 공지 시점에
존재하던 쪽으로만 판별하고, 그래도 둘이면 `release_unresolved.csv` 에 남긴다.

## 솔로 레이드 일정은 어떻게 정하나

업데이트 공지의 일정은 **계획**일 뿐이다. 실제로는 연기(8시즌), 중단 후 재오픈(19·
26·38), 몇 시간 중단 후 연장(28)이 있었고, 그 사실은 네이버 라운지 공지에만 있다.
그래서 모든 공지에서 오픈·재오픈·일정 변경·중단·연장·연기·기록 초기화 문장을
이벤트로 뽑고, 시즌별로 시간순 재생해서 **실제로 열려 있던 구간**을 만든다.

enikk 는 일정의 출처가 아니라 **검증 수단**이다. enikk 가 랭킹을 수집한 시각은
실제 플레이의 증거이므로, 복원한 구간 밖에서 수집됐거나 보스 속성이 다르면
`soloraid_seasons.csv` 의 `checks` 열에 남는다. 공지에 시즌 번호가 없는 초기 시즌
(1–25)은 enikk 수집 시각과 맞춰 번호를 붙인다. 자세한 규칙은
[docs/timeline.md](docs/timeline.md).

---

## 산출물

| 파일 | 한 행 | 내용 |
|---|---|---|
| `roster.csv` | 니케 | 이름·속성·풀네임, 출시일(`release_date`, `release_at`)과 그 출처·신뢰도 |
| `unit_releases.csv` | 니케 | 출시를 정한 공지와 그 문장 |
| `banners.csv` | 모집 기간 | 신규/재모집, 특수/한정/선택/이벤트 획득, 근거 문장 |
| `soloraid_seasons.csv` | 시즌 | 보스(EN/KO)·속성·약점, 처음 공지된 일정, 실제 시작·종료, 교란 여부, 그 시점 니케 수·신규 니케, enikk 대조 결과 |
| `soloraid_periods.csv` | 운영 구간 | 시즌별로 실제 열려 있던 구간과 끝난 이유(종료/중단/연장) |
| `soloraid_events.csv` | 공지 문장 | 일정의 근거 (오픈·중단·재오픈·연장·연기·초기화·이슈) |
| `season_calendar.csv` | 시즌 | 분석 단계가 읽는 시즌 달력 (자동 생성) |
| `notices.csv` | 공지 | 공식·네이버 공지 목록과 분류 |
| `unit_aliases.csv` | 표기 | 니케마다 알려진 모든 표기 |
| `timeline_issues.csv` | 점검 결과 | 규칙이 처리하지 못한 것, 약한 출처를 쓴 것 (`nikke check`) |

---

## 지표 (보류)

솔로레이드 랭킹이 들어오면 채울 지표. 정의와 근거는 [docs/metrics.md](docs/metrics.md).

| 지표 | 답하는 질문 |
|---|---|
| `weighted_pick_rate` | 상위권 근거 중 이 니케가 차지하는 비중 (순위 가중) |
| `lift` | 무작위 대비 몇 배 뽑히는가 (로스터 증가 보정) |
| `score_delta` | 이 니케를 쓴 팀이 **실제로** 점수가 높은가 |
| `tier_score` / `tier` | 위 세 축의 합성 점수와 등급 |
| `total_variation` | 시즌 사이 메타가 몇 % 움직였는가 |
| `pmi` (synergy) | 우연 이상으로 같이 쓰이는 조합 |

각 시즌은 **그때 출시돼 있던 유닛만** 분모로 쓴다. 이번 단계에서 만든 출시일과
시즌 달력이 그 분모다.

---

## 조정 가능한 것

판단이 들어가는 값은 코드가 아니라 파일에 있다.

| 파일 | 내용 |
|---|---|
| `data/manual/release_overrides.csv` | 출시일 수동 보정 (사유 필수, 공지 기반 날짜보다 우선) |
| `data/manual/unit_aliases.csv` | 자동으로 못 찾는 표기의 수동 별칭 |
| `config/tiers.yaml` | 티어 가중치와 컷 |
| `config/enikk.yaml` | 랭킹 수집 엔드포인트와 JSON 필드 매핑 |

---

## 출처

| 소스 | 쓰는 것 | 수집 |
|---|---|---|
| [nikke-kr.com](https://www.nikke-kr.com) 공지 (Level Infinite CMS) | 업데이트 공지: 신규 니케·모집 기간·솔로 레이드 일정 | `collect notices` |
| [네이버 게임 라운지](https://game.naver.com/lounge/nikke/board/11) 공지 게시판 | 운영 공지: 솔로 레이드 중단·재오픈·연장·연기 | `collect notices` |
| [enikk](https://enikk.app/soloraid) (GraphQL) | 시즌 보스·속성, 랭킹 수집 시계열, 캐릭터 속성 | `collect enikk-meta` |
| [nikke-forbidden-library](https://github.com/LiviaMedeiros/nikke-forbidden-library) | 유닛 ID, EN/KO/JA 공식 표기, 풀네임 | `collect roster` |
| [`@sancti0n/nikke-utils`](https://www.npmjs.com/package/@sancti0n/nikke-utils) | 속성, 데이터 등재일 | `collect roster` |

니케 본편은 Steam 에 없다(Steam 에는 스텔라 블레이드 콜라보 DLC 만 있다). 그래서
공지는 공식 채널에서 직접 받는다.

---

## 문서

- [docs/timeline.md](docs/timeline.md) — 출시일·솔로 레이드 달력 복원 규칙, 알려진 공백
- [docs/metrics.md](docs/metrics.md) — 지표 정의, 공식, 한계
- [docs/network-policy.md](docs/network-policy.md) — 네트워크 정책 여는 법
- [docs/enikk-setup.md](docs/enikk-setup.md) — 랭킹 사이트 연결 절차
