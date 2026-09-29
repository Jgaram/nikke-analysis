# enikk API 참고

> 2026-09-28 GraphQL 인트로스펙션과 저장된 응답으로 확인. 수집을 어떻게 돌리는지는
> [enikk-setup.md](enikk-setup.md), 여기는 사이트가 무엇을 주는지의 기록이다.

## 요약

| 항목 | |
|---|---|
| 프로토콜 | **POST GraphQL** — `https://enikk.app/api/graphql` (REST 경로 없음) |
| 인트로스펙션 | 열려 있음 — 스키마 전체를 요청 한 번으로 읽는다 |
| Query 필드 | 85개. 솔로 레이드 외에 캠페인·타워·챔피언 아레나·시뮬레이션 룸·유니온 레이드·협동 작전 |
| 범위 | 솔로 레이드 시즌 1부터 전부. 발표만 된 다음 시즌은 목록에만 있고 랭킹이 없다 |
| 서버 | 6개 — GLOBAL · JP · KR · NA · SEA · TW-HK (**시즌 5·6은 4개만** 추적됨) |
| 한 시즌 | **보스 하나.** 랭커마다 그 보스에 친 **덱 5개 × 5명 = 25칸** |

GET 으로 치면 `{"errors":[{"message":"Must provide query string."}]}` 가 온다.
이 프로젝트는 `util/http.py` 의 `Fetcher.post_json` 으로 보낸다.

## 스키마 읽는 법

추측할 필요가 없다.

```bash
curl -sS -X POST https://enikk.app/api/graphql \
  -H 'Content-Type: application/json' \
  -d '{"query":"{ __type(name:\"Query\"){ fields { name args { name type { name kind ofType { name kind } } } } } }"}'
```

## 솔로 레이드 필드

| 필드 | 인자 | 내용 | 여기서 |
|---|---|---|---|
| `soloRaidSummaries` | — | 시즌 목록, 보스, 보스 그림 이름(`monster_image`), 약점, `data.lastupdated` | 시즌 목록·증분 판단 (`collect enikk`, `collect enikk-meta`) |
| `SRRankings` | `raid`, `server`, `all`, `exclude` | 랭커별 총점 + 덱 5개 | **랭킹 본체** (`collect enikk`) |
| `soloRaid` | `raid` | 보스 웨이브·속성·약점 | 달력 교차검증 (`collect enikk-meta`) |
| `SRDamageChart` | `raid` | 서버별 수집 시각마다 최고·평균·최저 점수 | 수집 시계열 (`collect enikk-meta`) |
| `soloRaidLastUpdated` | `raid` | 한 시즌의 마지막 갱신 | 안 씀 (`soloRaidSummaries` 로 충분) |
| `SRCharacters` | `raid`, `allParses` | 사이트가 계산한 니케별 집계 | 안 씀 |
| `SRTeams`, `SRTeamsPage` | `raid`, `characters`(필수), … | 편성 단위 집계 | 안 씀 |
| `SRParses`, `SRParsesPage` | `raid`, `characters`(필수), … | 개별 기록 | 안 씀 |
| `SRBuildProfiles` | `raid`, `top` | 투자(코어·전투력) 프로필 | 안 씀 |
| `SRRankBands` | `raid`, `server`, `bandSize` | 순위 구간별 분포 | 안 씀 |
| `SRCharacterCPRanking`, `SRAllCharacterCPRankings` | `raid`, (`character`) | 니케별 전투력 순위 | 안 씀 |
| `SRGenerator`, `SRGeneratorOptimized` | `raid`, `characters`, … | 편성 추천기 | 안 씀 |
| `soloRaidEloLeaderboard`, `soloRaidEloPlayer` | `server`, … | 플레이어 Elo (메타와 다른 축) | 안 씀 |

"안 씀" 필드의 내용은 이름과 인자로 본 것이고 응답을 받아 검증하지는 않았다. 사이트가
자기 방식으로 계산한 값이라 정의가 공개돼 있지 않다 — 이 프로젝트는 원자료
(`SRRankings`)에서 직접 센다.

## `SRRankings` 응답

우리 쿼리는 [`config/enikk.yaml`](../config/enikk.yaml) 에 있다. `all` 을 넘기지 않으면
**서버별 상위 50명** — 6개 서버면 300명, 시즌 하나에 약 430KB. 시즌 40의 한 레코드:

```json
{
  "rank": 1,
  "playerid": "76133986",
  "server": "JP",
  "damage": 47768983534,
  "cp": 4579216,
  "collectionTime": "2026-08-28",
  "firstAppeared": "2026-08-26T18:44:00.000Z",
  "teams": [
    {
      "characters": ["…", "…", "…", "…", "…"],
      "damage": 7782912102,
      "cp": 951058,
      "cpc":   [ … 5개 ],
      "cores": [ … 5개 ],
      "percentile": 92.67,
      "cppercentile": 92.82,
      "count": 1969
    }
    // … 덱 5개
  ]
}
```

읽을 때 주의할 것:

- **`damage` 는 랭커 총점**(덱 5개의 합), `teams[].damage` 는 그 덱이 같은 보스에게 넣은
  대미지다. 대미지 0 인 덱은 **치지 않은 덱**이라 지표에서 뺀다.
- **`teams` 의 순서는 플레이어가 배치한 순서**이고 딜량 순이 아니다. 딜량 순위는
  `raid_entries` 에서 `deck_score` 로 다시 매긴다(`deck_rank`, [metrics.md](metrics.md)).
- `cpc`(칸별 전투력), `cores`(칸별 코어)는 투자 수준이다. "적게 쓰인다"가 약해서인지
  덜 키워서인지 가르려면 필요한 값이라 `raid_entries` 에 그대로 남겨 둔다.
- `percentile`, `cppercentile`, `count` 는 사이트가 계산한 값이다(정의 비공개, 안 씀).
- `collectionTime` 은 enikk 가 그 기록을 마지막으로 본 날, `firstAppeared` 는 처음 본
  시각이다. 둘 다 시즌 기간과 같지 않다 — 시즌이 끝났는지는 달력과
  `soloRaidSummaries` 의 `lastupdated` 로 판단한다.
- `all: true` 를 넘기면 enikk 가 우연히 조회한 **순위권 밖 플레이어**가 `rank: null`
  로 섞여 온다(2026-09-17 관측: 시즌 40 에 약 2,100명, 3MB). 정해진 모집단이 아니므로 쓰지 않는다.

## 보스 그림과 이름

`monster_image`(예 `full_eba002_hsta`)는 사이트가 `/bosses/<이름>.png` 로 띄우는 보스 그림이다
(약 1000px, 배경 투명, 한 장 약 900KB). 사이트 자신의 이미지 변환기
`/_next/image?url=%2Fbosses%2F<이름>.png&w=256&q=75` 를 `Accept: image/webp` 로 부르면 256px WebP
(약 30KB)가 온다 — 시즌 페이지가 요청하는 크기다. `collect enikk-meta` 가 보스마다 한 번 받아
`data/assets/icons/bosses/` 에 둔다.

보스 이름은 영어뿐이다. 언어를 고르는 인자가 없고 페이지도 `lang="en"` 이다. 한글 이름은
공지에서 나오면 그걸, 아니면 [`data/manual/boss_names.csv`](../data/manual/README.md#boss_namescsv) 를 쓴다.

## 니케 이름

영어 표시 이름을 준다 — `Rapi: Red Hood`, `Dorothy: Serendipity`, `2B`, `Queen (Makoto)`.
로스터 별칭 표로 거의 전부 1:1로 맞는다. 예외는 **두 니케가 같이 쓰는 이름 둘**
(`Rei` = 라이 392 / 레이 831, `Sakura` = 사쿠라 282 / 836)이다. 사이트의 `Rei` 는
레이(아야나미 레이)로 정해 두고, 나머지는 규칙으로 가른다 —
[enikk-setup.md의 이름 매칭](enikk-setup.md#이름-매칭).

## 수집 매너

개인이 운영하는 사이트다. 인트로스펙션이 열려 있는 것은 편의지 초대장이 아니다.
요청 간 1.5초, 끝난 시즌은 한 번만, 연락처가 담긴 User-Agent —
[enikk-setup.md의 수집 매너](enikk-setup.md#수집-매너).
