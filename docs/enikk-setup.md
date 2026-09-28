# enikk 랭킹 수집

[enikk](https://enikk.app/soloraid) 는 솔로 레이드 **서버별 상위 50명**의 점수와
**5개 덱 편성**, 덱별 대미지, 니케별 전투력·코어를 공개한다. 이 프로젝트에서
"실제로 뭐가 이기고 있는가"를 말해주는 유일한 소스다.

사람이 할 일은 없다. `nikke refresh`(와 CI)가 매번 새 시즌·바뀐 시즌만 받는다.

## 어떻게 받나

enikk 는 Next.js 앱이고 데이터는 전부 `POST /api/graphql` 에서 온다.

| 쿼리 | 쓰는 곳 | 수집 명령 |
|---|---|---|
| `soloRaidSummaries` | 시즌 목록, 시즌별 `lastupdated` (증분 판단) | `collect enikk`, `collect enikk-meta` |
| `SRRankings(raid)` | 서버별 상위 50명 × 5덱 (랭킹 본체) | `collect enikk` |
| `soloRaid`, `SRDamageChart` | 보스·속성·약점, 수집 시계열 (달력 교차검증) | `collect enikk-meta` |
| `/characters` 페이지 | 니케 속성 보충 | `collect enikk-meta` |

사이트가 주는 필드 전체와 응답의 모양·주의점은 [enikk-api.md](enikk-api.md) 에 있다.

랭킹 쿼리와 응답의 필드 위치는 코드가 아니라 [`config/enikk.yaml`](../config/enikk.yaml)
에 있다. 사이트가 필드 이름을 바꾸면 YAML 한 줄을 고치고 `nikke build raids` 를
다시 돌리면 되고, **이미 받아둔 시즌 스냅샷은 그대로 다시 파싱된다.**

```bash
nikke collect enikk                 # 새 시즌, lastupdated 가 바뀐 시즌(= 진행 중 시즌)만
nikke collect enikk --seasons 40 41 # 이 시즌들은 무조건 다시
nikke collect enikk --full          # 전 시즌 다시 (백필)
nikke build raids                   # 스냅샷 -> raid_entries.csv
```

- 끝난 시즌은 `lastupdated` 가 더 안 바뀌므로 한 번만 받는다. 진행 중 시즌은 매번 받는다.
- 아직 랭킹이 없는 시즌(발표만 된 다음 시즌)도 물어보지만 빈 응답은 저장하지 않는다.
- 받은 응답이 이전 스냅샷과 바이트 단위로 같으면 저장하지 않는다.
- 한 시즌이 실패해도 나머지는 저장되고, 실패한 시즌은 다음 실행 때 다시 묻는다.
  전부 실패하면 오류로 끝난다(`nikke refresh` 는 종료 코드 1).

스냅샷은 `data/raw/enikk_soloraid/<run>/season-NNN.json` 에 커밋된다. 시즌 1–41
전체가 약 17MB, 이후 매 실행은 진행 중 시즌 하나(약 430KB)만 더한다.

## 이름 매칭

enikk 는 니케를 영어 표시 이름으로 준다("Rapi: Red Hood", "Queen (Makoto)").
로스터의 별칭 표로 게임 ID에 맞추는데, **두 이름은 두 니케가 같이 쓴다**:
`Rei`(라이 / 레이 — 에반게리온 콜라보)와 `Sakura`(사쿠라 / 2025 콜라보 SR).
사이트는 어느 쪽인지 말하지 않는다.

어느 쪽인지 아는 이름은 `data/manual/ranking_names.csv` 에 정해 둔다. 지금은
`Rei` = 레이(831, 아야나미 레이) 하나다. 정한 니케가 출시된 뒤의 시즌에만
적용되므로, 레이가 나오기 전(2024-08-29 전) 시즌의 `Rei` 는 아래 규칙대로 라이가 된다.
문맥 규칙만으로는 수냉 약점 시즌의 `Rei` 를 라이로 보고(시즌 18·22·27·41),
몇 칸은 못 정했었다(시즌 19·20·23) — 덱을 보면 모두 아스카·마리와 같이 쓴 레이다.

정해 두지 않은 이름은 문맥으로 정한다, 순서대로:

1. 그 시즌 시작 전에 출시된 쪽만 남긴다.
2. 덱에 버스트 단계(I · II · III)가 하나 빠져 있으면 그 단계인 쪽.
3. 그 시즌 보스가 약한 속성인 쪽.

그래도 못 정하면 **추측하지 않고** `data/processed/raid_unresolved_names.csv` 에
남기고(지금은 없음), `nikke check` 가 경고로 보여 준다. 새 콜라보 니케처럼
로스터에 아직 없는 이름도 여기에 남는데, 보통 다음 로스터 갱신 때 저절로 풀린다.

## 사이트가 바뀌었을 때

쿼리가 오류를 내기 시작하면(`nikke refresh` 의 `collect.enikk.rankings` 실패):

```bash
nikke probe enikk
cat data/raw/enikk_probe/*/probe-report.json | jq '.findings[] | select(.is_json)'
```

probe 는 페이지·JS 번들·흔한 경로를 훑어 JSON 을 주는 곳을 기록한다(404 포함 전부
`data/raw/enikk_probe/` 에 저장). 새 쿼리나 필드 이름을 찾으면 `config/enikk.yaml`
의 `rankings.query` / `rankings.mapping` 을 고친다.

## 수집 매너

요청 간 1.5초(`delay`)를 쉬고, 실패 시 지수 백오프로 최대 4회 재시도하며, 연락처가
담긴 User-Agent 를 보낸다. 전체 백필도 42번 요청이다. `delay` 를 줄이지 말 것 —
개인이 운영하는 사이트다.
