# CLAUDE.md

## 브랜치는 main 하나

이 레포는 `main` 한 브랜치만 쓴다. 세션 작업 브랜치(`claude/...`)는 main 으로 가는
통로일 뿐이고, PR 은 따로 열 필요가 없다.

- 세션 브랜치에 push 하면 `.github/workflows/merge-to-main.yml` 이 그 커밋을 main 에
  합쳐 테스트를 돌리고, 통과하면 main 에 올린 뒤 세션 브랜치를 지운다. push 한 뒤
  원격에서 브랜치가 사라지는 건 정상이다. 다시 push 하면 다시 생기고 또 합쳐진다.
- 그러니 push 가 곧 main 반영이다. push 전에 테스트를 돌린다
  (`pip install -e ".[dev]"` 한 번, 그다음 `python -m pytest -q`).
- 합치기가 실패하면(충돌이나 테스트 실패) main 은 그대로이고 세션 브랜치가 남는다.
  push 한 뒤 Actions 의 `merge-to-main` 실행 결과를 확인하고, 실패했으면
  `git fetch origin main && git merge origin/main` 으로 최신 main 을 받아 고친 뒤
  다시 push 한다.
- main 에는 `refresh` 워크플로도 주 2회 데이터 커밋을 올린다. 세션이 길어졌으면
  push 전에 위 명령으로 main 을 따라잡는다.
- 새 브랜치를 따로 만들지 않는다. 자동 병합은 `claude/` 로 시작하는 브랜치만 한다.
