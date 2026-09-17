# nikke-analysis

승리의 여신: 니케의 **메타·티어 변화**를 패치 단위로 추적하는 파이프라인.
솔로레이드 상위 랭킹 데이터를 지표화해서 "지금 뭐가 강한가"가 아니라
**"무엇이, 언제, 왜 바뀌었는가"** 를 답하는 것이 목표.

핵심 제약 하나: **런타임에 AI를 쓰지 않는다.** 새 패치와 새 시즌은 사람이
읽고 판단해서가 아니라 `nikke refresh` 한 번으로 반영된다.

---

## 지금 상태

| 단계 | 상태 |
|---|---|
| 로스터(니케 202명 + 출시일 + EN/KO/JA 이름) | ✅ 동작, 데이터 커밋됨 |
| 패치노트 수집·파싱 | ✅ 코드·테스트 완료 / ⚠️ 수집은 네트워크 필요 |
| enikk 솔로레이드 수집 | ⚙️ probe 도구 완료, 엔드포인트 1회 확인 필요 |
| 지표·티어 엔진 | ✅ 동작, 합성 데이터로 검증 (테스트 65개) |
| 시각화 | ✅ 라이트/다크 차트 5종 |
| CI 자동 갱신 | ✅ `.github/workflows/refresh.yml` |

`data/processed/roster.csv` 는 실제로 생성된 데이터다. 나머지 지표 테이블은
솔로레이드 데이터가 들어오면 같은 명령으로 채워진다.

---

## 빠른 시작

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

nikke refresh          # 수집 → 빌드 → 분석 → 차트, 의존 순서대로 전부
nikke status           # 지금 디스크에 뭐가 있는지
pytest -q              # 65 tests
```

개별 단계로 돌릴 수도 있다:

```bash
nikke collect roster            # 게임 파일 + nikke-utils
nikke collect patchnotes        # Steam 공지 API
nikke probe enikk               # 랭킹 사이트 API 정찰 (최초 1회)
nikke collect enikk --seasons 40 41
nikke build roster              # → roster.csv, unit_aliases.csv
nikke build patches             # → patches.csv, patch_events.csv, unit_releases.csv
nikke build raids               # → raid_entries.csv
nikke analyze                   # → metrics_*.csv
nikke viz                       # → reports/*.png
```

> **네트워크**: 클라우드 세션의 기본 `Trusted` 정책은 GitHub·패키지 레지스트리만
> 허용해서 enikk와 공식 공지에 닿지 못한다. 여는 방법은
> [docs/network-policy.md](docs/network-policy.md).

---

## 구조

네 단계가 한 방향으로만 흐른다. 각 단계의 입력은 항상 **디스크 위의 파일**이고,
같은 입력이면 같은 출력이 나온다.

```
collect/   네트워크 → data/raw/        가져오기만 한다. 해석하지 않는다.
build/     raw      → data/processed/  순수 파싱·조인
analyze/   processed → metrics_*.csv   순수 계산
viz/       metrics  → reports/*.png    렌더링
```

`collect` 가 아무것도 해석하지 않는 게 중요한 이유:

- 사이트 마크업은 예고 없이 바뀐다. 파서가 깨져도 **이미 받아둔 스냅샷**으로
  고쳐서 다시 돌리면 된다.
- 솔로레이드 랭킹은 **휘발성**이다. 시즌이 넘어가면 이전 top-50은 사이트에서
  사라진다. 시즌 중에 찍어둔 스냅샷이 유일한 사본이 된다.
- 파서가 `bytes → records` 순수 함수가 되어 네트워크 없이 테스트된다.

### 데이터 흐름의 두 개 축

```
      게임 파일 (EN/KO/JA 이름) ─┐
                                 ├→ roster.csv ─┐
      nikke-utils (속성/날짜) ───┘               │
                                                 ├→ 지표 → 티어 → 차트
      Steam 공지 → patches.csv ──┐               │
                                 ├→ 출시일 ──────┘
      enikk → raid_entries.csv ──┘
```

로스터를 **두 번** 빌드한다. 출시일은 패치노트에서 오는데, 패치노트에서 니케
이름을 찾으려면 로스터가 만든 별칭 테이블이 필요하다. 순환 의존을 만드는 대신
싼 패스를 두 번 돈다: 로스터(이름) → 패치(날짜) → 로스터(날짜 반영).

---

## 왜 unit_id 로 조인하는가

소스마다 표기가 다 다르다. 게임 파일은 `Rapi: Red Hood` / `라피 : 레드 후드`,
패치노트는 `Red Hood`, 랭킹 사이트는 커뮤니티 약칭을 쓴다. 이름이 어긋나면
채용률 자체가 무의미해진다.

그래서 모든 것은 **게임 내부 ID** 로 모인다 (`c016_00` → `016`). 언어와 무관하고,
바뀌지 않고, 이미 원본과 파생형을 구분한다 — `010` 라피와 `016` 레드후드는
메타에서도 별개 유닛이므로 그게 맞는 단위다.

이름 해석은 **절대 추측하지 않는다.** 모르는 표기는 조용히 버리는 대신
`raid_unresolved_names.csv` 에 남는다. 잘못 합쳐진 이름 하나가 그 위에 쌓인
모든 지표를 오염시키기 때문이다.

---

## 지표

자세한 정의와 근거는 [docs/metrics.md](docs/metrics.md). 요약하면:

| 지표 | 답하는 질문 |
|---|---|
| `weighted_pick_rate` | 상위권 근거 중 이 니케가 차지하는 비중 (순위 가중) |
| `lift` | 무작위 대비 몇 배 뽑히는가 (로스터 증가 보정) |
| `score_delta` | 이 니케를 쓴 팀이 **실제로** 점수가 높은가 |
| `tier_score` / `tier` | 위 세 축의 합성 점수와 등급 |
| `total_variation` | 시즌 사이 메타가 몇 % 움직였는가 |
| `newcomer_share` | 그 움직임 중 신규 니케 몫 |
| `top_k_churn` | 티어표를 얼마나 다시 써야 하는가 |
| `pmi` (synergy) | 우연 이상으로 같이 쓰이는 조합 |
| `retention` | 전성기 대비 지금 얼마나 남았는가 (파워 크리프) |

**출시일이 지표의 핵심 부품인 이유**: 존재하지 않던 시즌에 "안 뽑혔다"고
세면 오래된 니케일수록 부당하게 나빠 보인다. 그래서 각 시즌은 **그때 출시돼
있던 유닛만** 분모로 쓴다.

---

## 조정 가능한 것

판단이 들어가는 값은 전부 설정 파일에 있다. 코드를 고칠 일이 아니다.

| 파일 | 내용 |
|---|---|
| `config/tiers.yaml` | 티어 가중치와 컷 |
| `config/enikk.yaml` | 랭킹 사이트 엔드포인트와 JSON 필드 매핑 |
| `data/manual/release_overrides.csv` | 출시일 수동 보정 (사유 필수) |
| `data/manual/season_calendar.csv` | 시즌별 기간 |

---

## 출처

| 소스 | 쓰는 것 | 접근 |
|---|---|---|
| [nikke-forbidden-library](https://github.com/LiviaMedeiros/nikke-forbidden-library) | 유닛 ID, EN/KO/JA 공식 표기 | GitHub (항상 가능) |
| [`@sancti0n/nikke-utils`](https://www.npmjs.com/package/@sancti0n/nikke-utils) | 버스트/클래스/속성/제조사, 데이터파일 등재일 | npm (항상 가능) |
| Steam 공지 API | 패치노트·이벤트·출시일 | 도메인 허용 필요 |
| [enikk](https://enikk.app/soloraid) | 솔로레이드 상위 랭킹과 편성 | 도메인 허용 필요 |

---

## 문서

- [docs/metrics.md](docs/metrics.md) — 지표 정의, 공식, 한계
- [docs/network-policy.md](docs/network-policy.md) — 네트워크 정책 여는 법
- [docs/enikk-setup.md](docs/enikk-setup.md) — 랭킹 사이트 연결 절차
