# enikk 연결 절차

[enikk](https://enikk.app/soloraid) 는 솔로레이드 전섭 상위 랭커의 점수와
**5인 편성**을 공개한다. 이 프로젝트에서 "실제로 뭐가 이기고 있는가"를 말해주는
유일한 소스다.

수집기는 엔드포인트 모양을 코드가 아니라 `config/enikk.yaml` 에서 읽는다.
사이트가 구조를 바꾸면 YAML 한 줄을 고치고 다시 돌리면 되고, **이미 받아둔
시즌 스냅샷은 그대로 다시 파싱된다.** 랭킹은 시즌이 지나면 사라지기 때문에
이 성질이 중요하다.

최초 1회만 아래를 하면 된다.

> **2026-09 확인 결과.** enikk 는 Next.js App Router 앱이고, 데이터는 전부
> `POST /api/graphql` 에서 온다. 시즌 메타(`soloRaidSummaries`, `soloRaid`)와 수집
> 시계열(`SRDamageChart`), 캐릭터 표(`/characters` 페이지)는 이미
> `nikke collect enikk-meta` 로 수집한다 — 솔로 레이드 달력의 교차검증용이다.
> 랭킹 자체는 `SRRankings(raid, all)` 쿼리가 서버별 상위 50명과 5개 팀 편성을
> 준다. 지표 단계에서 이 쿼리를 수집기에 연결할 예정이며, 아래 REST 템플릿 방식은
> 그 전까지의 설정 틀이다. 과거 시즌도 enikk 에 남아 있다(시즌 1–40 확인).

## 1. 정찰

```bash
nikke probe enikk
```

probe 는 순서대로 이렇게 움직인다.

1. `/soloraid`, `/soloraid/ranker` 를 받아온다. Next.js 앱이면 `__NEXT_DATA__`
   안에 **랭킹이 통째로 들어있는 경우**가 많고, 최소한 `buildId` 는 나온다.
2. 페이지가 로드하는 JS 번들을 긁어서 `/api/...` 문자열 리터럴을 찾는다.
   앱은 자기가 부르는 주소를 어딘가에 적어둘 수밖에 없으므로 보통 여기서 나온다.
3. `buildId` 를 얻었으면 `/_next/data/<buildId>/<route>.json` 을 시도한다.
4. 마지막으로 흔한 경로들을 무작정 찔러본다.

모든 응답은 404까지 포함해서 `data/raw/enikk_probe/<run>/` 에 저장되고,
요약이 `probe-report.json` 에 남는다.

```bash
cat data/raw/enikk_probe/*/probe-report.json | jq '.findings[] | select(.is_json)'
```

## 2. config 채우기

JSON을 주는 엔드포인트를 하나 고르고, 응답을 열어서 필드 위치를 적는다.

```bash
jq . data/raw/enikk_probe/<run>/012-api_soloraid.json | head -60
```

`config/enikk.yaml`:

```yaml
base_url: https://enikk.app
endpoint_template: "/api/soloraid?season={season}&boss={boss}"
seasons: ["38", "39", "40"]
bosses: ["boss1", "boss2", "boss3", "boss4", "boss5"]

mapping:
  entries: data.rankers[]     # 랭킹 레코드 배열
  rank: rank
  score: damage
  player: nickname
  team: team[]                # 레코드 안의 유닛 배열
  unit_name: name             # 유닛 원소 안의 이름 필드
  unit_id: ""                 # 사이트가 게임 ID를 준다면 여기에 (이름 매칭보다 정확)
  boss: boss
  season: season
```

경로 문법은 점 표기법이고 `[]` 는 "이 리스트를 펼친다"는 뜻이다.
`data.rankers[].team[].name` 이면 응답 안의 모든 유닛 이름을 뜻한다.
키가 없으면 예외 대신 빈 값이 된다 — 응답 일부가 비어도 필드 하나만 잃지,
시즌 전체를 잃지는 않도록.

`unit_id` 를 채울 수 있으면 채우는 게 낫다. 이름 매칭을 건너뛰기 때문에
표기 흔들림에 영향을 받지 않는다.

## 3. 수집과 검증

```bash
nikke collect enikk --seasons 40
nikke build raids
```

빌드 결과의 `unresolved_names` 를 반드시 본다.

```bash
cat data/processed/raid_unresolved_names.csv
```

여기에 이름이 남았다는 건 **그 니케가 모든 채용률에서 통째로 빠졌다**는 뜻이다.
조용히 버려지지 않고 파일로 남는 이유가 그것이다. 해결은 둘 중 하나:

- 게임 파일 표기와 다른 커뮤니티 약칭이면 → 별칭을 추가한다.
- 신규 니케라 로스터에 아직 없으면 → `nikke collect roster` 를 다시 돌린다.

## 4. 이후

```bash
nikke refresh --seasons 41
```

새 시즌이 열릴 때마다 이것만 돌리면 된다. 사람이 판단할 부분은 없다.

## 수집 매너

`Fetcher` 는 기본적으로 요청 간 1.5초를 쉬고, 실패 시 지수 백오프로 최대 4회
재시도하며, 연락처가 담긴 User-Agent를 보낸다. 전체 백필도 수백 요청 수준이다.
`delay` 를 줄이지 말 것 — 개인이 운영하는 사이트다.
