"""Is a refresh due now? The hourly check behind the scheduled workflow.

The full ``nikke refresh`` runs on Monday and Thursday whatever happens, which
is what picks up a new notice. Between those, the rankings have two moments a
few days' wait would cost:

* a season being played - its tiers are only as current as the last read, so
  it is read once a day (``LIVE_EVERY``).
* a season that just ended - its final ranking is the one that counts. enikk
  usually posts it 1-3 hours after the end (06:00 or 08:00 KST for a 04:59
  end), but has taken up to four days, so it is asked about every hour until
  enikk's stamp for it has moved past the end, for at most ``FINAL_WITHIN``.
  After that ``nikke check`` reports the season (``ranking_not_final``).

Both are read off what is already on disk - the season's dates from the
notices, the stored snapshots' ``lastupdated`` - plus one request for enikk's
season list. A season ending on another weekday, or extended, needs nothing
done: the dates come from the notices.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from .paths import processed_dir

log = logging.getLogger(__name__)

LIVE_EVERY = timedelta(hours=20)  # "once a day", with room for a scheduled run starting late
FINAL_WITHIN = timedelta(days=7)

__all__ = ["Due", "FINAL_WITHIN", "LIVE_EVERY", "check", "decide"]


@dataclass
class Due:
    due: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"due": self.due, "reasons": self.reasons}


def _instant(text: Any) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def decide(
    now: datetime,
    seasons: list[Mapping[str, str]],
    stored: Mapping[int, Mapping[str, Any]],
    listed: Mapping[int, str],
) -> Due:
    """``seasons``: rows of soloraid_seasons.csv; ``stored``: the newest snapshot's meta per season
    (``lastupdated``, ``fetched_at``); ``listed``: enikk's ``lastupdated`` per season, now."""
    reasons = []
    for row in seasons:
        try:
            number = int(row["season"])
        except (KeyError, ValueError):
            continue
        start, end = _instant(row.get("start_at")), _instant(row.get("end_at"))
        if start is None or now < start:
            continue
        stamp = listed.get(number, "")
        previous = stored.get(number, {})
        if not stamp or stamp == previous.get("lastupdated"):
            continue  # enikk has nothing newer than what is on disk
        if end is None or now < end:
            fetched = _instant(previous.get("fetched_at"))
            if fetched is None or now - fetched >= LIVE_EVERY:
                reasons.append(f"시즌 {number} 진행 중 · 하루 한 번 순위 갱신")
        elif now - end < FINAL_WITHIN:
            have = _instant(previous.get("lastupdated"))
            if have is None or have < end:
                reasons.append(f"시즌 {number} 종료 · 끝난 뒤의 순위가 올라옴 (enikk {stamp})")
    return Due(bool(reasons), reasons)


def check(now: datetime, directory: Path | None = None) -> Due:
    """``decide`` on what is on disk and enikk's season list. When enikk cannot be reached the answer
    is "not due": the Monday/Thursday refresh is the one that reports an outage."""
    from .collect import enikk
    from .config import load_enikk_config
    from .util.http import Fetcher

    path = (directory or processed_dir()) / "soloraid_seasons.csv"
    if not path.is_file():
        return Due(True, ["soloraid_seasons.csv 없음 · 처음부터 갱신"])
    with path.open(encoding="utf-8", newline="") as handle:
        seasons = list(csv.DictReader(handle))
    config = load_enikk_config()
    try:
        listed = enikk._summaries(Fetcher(delay=config.delay), config.base_url)
    except Exception as exc:  # network policy, outage, a changed API
        log.warning("enikk season list unavailable: %s", exc)
        return Due(False, [f"enikk 시즌 목록을 못 받음 ({exc}) · 정기 갱신에서 보고"])
    return decide(now, seasons, enikk._stored_rankings(), listed)
