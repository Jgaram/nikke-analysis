"""Is the automation still keeping up on its own?

The timeline is built by fixed rules, not by anyone reading the notices. That
holds as long as the notices keep the shapes the rules know - and they have,
from the 2022 launch to now. When a shape changes (a new way of naming a unit,
new wording for a suspended season, an API that moved), the rules do not guess:
the item is left out, and this report is where that becomes visible. An
unattended run should end red when the timeline may have stopped being right,
not quietly green.

Two kinds of finding:

* **Data findings**, derived from the processed tables alone. Deterministic, so
  they are written next to the tables as ``timeline_issues.csv``.
* **Run findings**, which depend on when the check runs: a collector that
  failed, or no new update notice / Solo Raid season for longer than the game
  ever goes without one.

Levels: ``error`` means the timeline may be wrong or stale - a scheduled run
exits non-zero on one. ``warning`` means a known kind of gap (a date taken from a
weaker source, a name no rule resolved). ``info`` is expected and harmless, such
as a unit that is in the game files but not announced yet.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from .paths import processed_dir

ISSUES_CSV = "timeline_issues.csv"

# Updates have come every two to three weeks since launch; Solo Raid seasons at
# most 42 days apart. Silence well past that means collection or parsing stopped.
UPDATE_NOTICE_MAX_GAP = timedelta(days=45)
SEASON_MAX_GAP = timedelta(days=60)

ENIKK_DISAGREEMENTS = (
    "enikk_after_periods",
    "enikk_before_periods",
    "enikk_outside_periods",
    "element_mismatch",
    "weakness_mismatch",
)
LEVELS = ("error", "warning", "info")


@dataclass(frozen=True)
class Issue:
    level: str
    code: str
    subject: str
    detail: str


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def data_issues(directory: Path, problems: Iterable[str] = ()) -> list[Issue]:
    """Findings that follow from the processed tables (and the build's own problems)."""
    issues = [Issue("error", "season_numbering", "", problem) for problem in problems]

    for row in _rows(directory / "soloraid_seasons.csv"):
        checks = [c for c in row.get("checks", "").split(";") if c]
        subject = f"시즌 {row['season']}"
        if "no_notice" in checks and row.get("enikk_first_seen"):
            issues.append(
                Issue("error", "season_played_without_notice", subject,
                      "enikk 가 플레이를 관측했지만 어떤 공지에서도 일정을 찾지 못했다")
            )
        disagreements = [c for c in checks if c.split(":")[0] in ENIKK_DISAGREEMENTS]
        if disagreements:
            issues.append(Issue("warning", "enikk_disagrees", subject, ", ".join(disagreements)))

    for row in _rows(directory / "release_unresolved.csv"):
        issues.append(Issue("warning", "unresolved_name", row["name"], row["notice_title"]))

    for row in _rows(directory / "roster.csv"):
        name = row.get("name_ko") or row.get("name_en") or row["unit_id"]
        source = row.get("release_date_source", "")
        if source.startswith("datafile"):
            issues.append(
                Issue("warning", "release_from_datafile", name,
                      f"{row['release_date']} (공지 기반 출시일 없음, 데이터 등재일 사용)")
            )
        elif not source:
            issues.append(Issue("info", "unit_without_date", name, "게임 데이터에만 있고 아직 공지·등재일 없음"))
        if not (row.get("element") and row.get("unit_class")):
            issues.append(Issue("warning", "unit_without_attributes", name, "속성·클래스 미확인"))

    return sorted(issues, key=lambda i: (LEVELS.index(i.level), i.code, i.subject, i.detail))


def run_issues(directory: Path, now: datetime, failures: dict[str, str] | None = None) -> list[Issue]:
    """Findings that depend on the moment of the check."""
    issues = [Issue("error", "collector_failed", step, message) for step, message in (failures or {}).items()]

    updates = [r["published_at"] for r in _rows(directory / "notices.csv") if r.get("kind") == "update"]
    if not updates:
        issues.append(Issue("error", "notices_missing", "", "업데이트 공지가 하나도 없다"))
    else:
        newest = datetime.fromisoformat(max(updates))
        if now - newest > UPDATE_NOTICE_MAX_GAP:
            issues.append(
                Issue("error", "notices_stale", "", f"마지막 업데이트 공지가 {newest.date()} — 수집이나 분류가 멈췄을 수 있다")
            )

    starts = [r["start_at"] for r in _rows(directory / "soloraid_seasons.csv") if r.get("start_at")]
    if starts:
        newest_start = datetime.fromisoformat(max(starts))
        if now - newest_start > SEASON_MAX_GAP:
            issues.append(
                Issue("error", "soloraid_stale", "",
                      f"가장 최근 시즌 시작이 {newest_start.date()} — 새 시즌 공지를 읽지 못하고 있을 수 있다")
            )
    return issues


def ranking_issues(directory: Path, now: datetime) -> list[Issue]:
    """Findings about the Solo Raid rankings behind the tiers.

    A name no rule matched drops that unit from every number of the seasons it
    appears in, and a played season without rankings is a hole in every trend
    line - neither makes the timeline wrong, so both are warnings.
    """
    issues = [
        Issue(
            "warning",
            "ranking_name_unresolved",
            row["name"],
            f"{row['occurrences']}칸 · 시즌 {row['seasons']} · 후보 {row['candidates'] or '없음'} — 이 칸은 지표에서 빠진다",
        )
        for row in _rows(directory / "raid_unresolved_names.csv")
    ]
    ranked = {row["season"] for row in _rows(directory / "metrics_seasons.csv") if row.get("rankers") not in (None, "", "0")}
    if ranked:
        for row in _rows(directory / "soloraid_seasons.csv"):
            end = row.get("end_at")
            if end and row.get("enikk_first_seen") and datetime.fromisoformat(end) <= now and row["season"] not in ranked:
                issues.append(Issue("warning", "ranking_missing", f"시즌 {row['season']}", "끝난 시즌인데 랭킹 스냅샷이 없다"))
    return issues


def write(directory: Path, issues: Iterable[Issue]) -> Path:
    path = directory / ISSUES_CSV
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(Issue.__dataclass_fields__))
        writer.writeheader()
        for issue in issues:
            writer.writerow(asdict(issue))
    return path


def read(directory: Path | None = None) -> list[Issue]:
    return [Issue(**row) for row in _rows((directory or processed_dir()) / ISSUES_CSV)]


def has_errors(issues: Iterable[Issue]) -> bool:
    return any(issue.level == "error" for issue in issues)


LEVEL_KO = {"error": "오류", "warning": "경고", "info": "참고"}


def render(issues: list[Issue]) -> str:
    counts = {level: sum(1 for i in issues if i.level == level) for level in LEVELS}
    head = " · ".join(f"{LEVEL_KO[level]} {counts[level]}" for level in LEVELS)
    if counts["error"]:
        verdict = "확인 필요 — 자동 갱신 결과를 그대로 믿으면 안 되는 상태"
    else:
        verdict = "정상 — 사람이 볼 필요 없음" if not counts["warning"] else "정상 (알려진 공백만 있음)"
    lines = [f"상태 점검: {verdict}  ({head})"]
    for issue in issues:
        subject = f"{issue.subject}: " if issue.subject else ""
        lines.append(f"  [{LEVEL_KO[issue.level]}] {issue.code}  {subject}{issue.detail}")
    return "\n".join(lines)
