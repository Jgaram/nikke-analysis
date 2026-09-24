# 네트워크 정책 여는 법

이 프로젝트가 접속하는 곳은 다섯 곳이다. 클라우드 세션의 기본 **Trusted** 정책은
패키지 레지스트리와 GitHub 만 허용하므로, 공지 CMS·네이버 라운지·enikk 는 막힌다.

증상은 이렇게 보인다:

```
curl: (56) CONNECT tunnel failed, response 403
```

```bash
curl -sS "$HTTPS_PROXY/__agentproxy/status" | jq .recentRelayFailures
# → "gateway answered 403 to CONNECT (policy denial or upstream failure)"
```

## 고치는 법

네트워크 접근은 **환경(Environment) 단위 설정**이다. 세션 단위가 아니다.

1. claude.ai/code 에서 환경 선택 아이콘(클라우드 모양)을 눌러 환경 편집을 연다.
2. **Network access** 를 `Custom` 으로 바꾼다.
3. **Allowed domains** 에 아래를 한 줄씩 넣는다.
4. **"Also include default list of common package managers"** 를 체크한다.
   (체크를 빼면 pip·npm·GitHub까지 같이 막혀서 빌드가 깨진다.)
5. 저장한 뒤 **새 세션을 시작한다.** 컨테이너는 세션 시작 시점에 프로비저닝되므로
   실행 중인 세션에는 적용되지 않는다.

`Full` 을 골라도 되지만, 목록을 적어두면 이 프로젝트가 실제로 어디에 접속하는지가
문서로 남는다.

## 허용할 도메인

```text
na-community.playerinfinite.com
comm-api.game.naver.com
enikk.app
```

| 도메인 | 쓰는 곳 |
|---|---|
| `na-community.playerinfinite.com` | nikke-kr.com 공지사항·뉴스의 실제 데이터 (Level Infinite CMS API) — `collect/notices.py` |
| `comm-api.game.naver.com` | 네이버 게임 라운지 공지 게시판 API — `collect/notices.py` |
| `enikk.app` | 솔로 레이드 시즌 메타·수집 시계열·캐릭터 표 (GraphQL), 이후 랭킹 — `collect/enikk.py` |

니케 본편은 Steam 에 없으므로 Steam API 는 쓰지 않는다.

## 허용 목록 밖에서도 되는 것

정책과 무관하게 항상 닿는 경로가 있다. 로스터를 `Trusted` 환경에서도 만들 수
있는 이유다.

- **GitHub** — 게임 파일 미러(`nikke-forbidden-library`)를 `git clone` 한다.
- **패키지 레지스트리** — `@sancti0n/nikke-utils` 를 npm 에서 받는다.
- **Anthropic API** — Claude Code 자체 통신.

## 정책을 안 열고 가는 길

`.github/workflows/refresh.yml` 은 같은 `nikke refresh` 를 GitHub Actions에서
돌린다. Actions 러너는 아웃바운드 제한이 없으므로, 수집을 전부 CI에 맡기고
클라우드 세션은 코드 작업만 해도 된다. 공지 스냅샷과 갱신된 표가 그대로 커밋되므로
세션에서는 `git pull` 만 하면 최신 데이터로 `nikke asof` 를 쓸 수 있다.
