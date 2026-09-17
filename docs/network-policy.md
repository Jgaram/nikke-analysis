# 네트워크 정책 여는 법

이 프로젝트는 클라우드 세션에서만 굴리는 것을 전제로 한다. 그런데 클라우드
환경의 기본 네트워크 정책이 **Trusted** 라서, 패키지 레지스트리와 GitHub만
허용되고 `enikk.app` 이나 공식 공지 사이트는 프록시에서 403으로 막힌다.

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
enikk.app
*.enikk.app
api.steampowered.com
store.steampowered.com
nikke-en.com
*.nikke-en.com
nikke-kr.com
*.blablalink.com
```

| 도메인 | 쓰는 곳 |
|---|---|
| `enikk.app` | 솔로레이드 상위 랭킹과 편성 (`collect/enikk.py`) |
| `api.steampowered.com` | ISteamNews 공지 API — 패치노트의 주 소스 |
| `store.steampowered.com` | Steam 앱 ID 확인 |
| `nikke-en.com` | 공식 공지 (Steam 공지가 축약본일 때의 보완) |
| `*.blablalink.com` | 공식 커뮤니티 공지 (선택) |

## 허용 목록 밖에서도 되는 것

정책과 무관하게 항상 닿는 경로가 있다. 이 프로젝트가 로스터를 `Trusted` 환경에서도
만들 수 있는 이유다.

- **GitHub** — 전용 프록시를 탄다. `git clone` 과 `raw.githubusercontent.com` 은
  공개 레포라면 언제나 된다.
- **패키지 레지스트리** — npm·PyPI 등.
- **Anthropic API** — Claude Code 자체 통신.

## 정책을 안 열고 가는 길

`.github/workflows/refresh.yml` 은 같은 `nikke refresh` 를 GitHub Actions에서
돌린다. Actions 러너는 아웃바운드 제한이 없으므로, 수집을 전부 CI에 맡기고
클라우드 세션은 코드 작업만 해도 된다. 오히려 이쪽이 스냅샷 히스토리가 레포에
쌓인다는 점에서 낫다.
