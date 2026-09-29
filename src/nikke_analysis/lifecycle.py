"""A unit's career across the element rotation - a study beside the tiers.

    python -m nikke_analysis.lifecycle     the numbers in docs/lifecycle.md, from the committed tables

Questions the tiers raise but do not answer (docs/lifecycle.md has the
answers as of the committed data):

**How general is a unit, and which way is its career going?** The tables
carry how general (``analyze.tiers.generality``, the columns ``generality``
and ``generality_band`` of the overall table); the study replays it season by
season. Which way a career went is the study's own (``careers``): it counts
which path generalists took.

**How close is retirement?** ``own_outlook``: every time a unit was fielded in a
season of its own element, whether the next season of that element fielded it
too, by the season tier it had in the first. ``at_risk`` puts the rates on the
units in use now: the chance that their next own-element season passes them by,
which is what retires them (``analyze.tiers.lifespans``).

**Could retirement be read off the tiers?** ``retirement_rules`` replays other
rules season by season against what happened after.

**What shape does a whole career take?** ``curves``: the generality of each turn
of the element rotation (``rotations``), without the tiers' memory - unused,
narrow from the start, general then narrowed to its own element, or general
all the way down.

**Does the meta follow the boss's weakness more than it did?** ``meta_index``
per season, ``debuts`` per unit's first year.

The study does not split units by role, nor by class: the class has too many
exceptions to stand for the role, and the role is not two groups but a matter
of degree - how much of what a unit adds is its own damage. That needs damage
per unit, which the rankings do not give (they give a deck's).

Nothing computed only here feeds the tiers, the committed tables or the tier site.
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

from .analyze import tiers
from .analyze.metrics import ELEMENTS

OUTLOOK_TIERS = ["S 이상", "A", "B", "C", "D 이하"]  # own-season tiers for the outlook: SS and S, ..., D and F together
USAGE_RULE = 0.10  # the lifespan rule before the season tier: fielded by a tenth of the rankers


def _flags(rows: pd.DataFrame, column: str) -> pd.Series:
    return tiers.flags(rows, column)


def _true(values: pd.Series) -> pd.Series:
    """A flag column that may have gaps (a unit missing from a merge) as booleans, a gap False."""
    return values.eq(True)


def _counted_rows(history: pd.DataFrame, seasons: pd.DataFrame, moment: Any, config: tiers.TierConfig) -> pd.DataFrame:
    """The season rows counted at ``moment``, with ``used`` (``tiers.fielded``), ``own`` and ``live``."""
    counted = tiers.counted_seasons(seasons, moment, config)
    rows = history[history["season"].isin(counted["season"])].copy()
    rows["used"] = tiers.fielded(rows, config)
    rows["own"] = _flags(rows, "element_match")
    rows["live"] = rows["season"].isin(counted.loc[counted["live"], "season"])
    return rows.sort_values(["unit_id", "season"])


# --------------------------------------------------------------------------
# how close retirement is
# --------------------------------------------------------------------------

def outlook_tier(lift: float, config: tiers.TierConfig) -> str:
    """The season tier of an own-element season, with SS and S together and D with F."""
    label = tiers.assign_tier(lift, config)
    order = config.tier_order
    if label in order[:2]:
        return OUTLOOK_TIERS[0]
    if label in order[-2:]:
        return OUTLOOK_TIERS[-1]
    return label


def own_outlook(history: pd.DataFrame, seasons: pd.DataFrame, config: tiers.TierConfig | None = None) -> pd.DataFrame:
    """Every pair of consecutive own-element seasons of a unit where the first fielded it:
    its lift and season tier (``outlook_tier``) there, and whether the second passed it by
    (``stopped``). The second must be over - a season in progress has not decided it yet."""
    config = config or tiers.TierConfig()
    rows = _counted_rows(history, seasons, seasons["end_at"].max(), config)
    final = set(seasons.loc[seasons["final"].astype(bool), "season"])
    own = rows[rows["own"]]
    pairs = own.assign(next_season=own.groupby("unit_id")["season"].shift(-1),
                       next_used=own.groupby("unit_id")["used"].shift(-1))
    pairs = pairs[pairs["used"] & pairs["next_season"].isin(final)]
    pairs = pairs.assign(tier=pairs["lift"].map(lambda v: outlook_tier(v, config)),
                         stopped=~pairs["next_used"].astype(bool), next_season=pairs["next_season"].astype(int))
    return pairs[["unit_id", "season", "lift", "tier", "next_season", "stopped"]].reset_index(drop=True)


def stop_rates(outlook: pd.DataFrame) -> pd.DataFrame:
    """Of the units fielded in an own-element season, how many the next one passed by, by tier."""
    rates = outlook.groupby("tier")["stopped"].agg(["size", "mean"]).rename(columns={"size": "n", "mean": "rate"})
    return rates.reindex(OUTLOOK_TIERS).dropna()


def rotation_gaps(seasons: pd.DataFrame) -> pd.Series:
    """Days between the starts of two seasons of the same boss weakness, median per weakness."""
    frame = seasons.dropna(subset=["start_at"]).sort_values("season")
    frame = frame.assign(gap=frame.groupby("weak_element")["start_at"].diff().dt.days)
    return frame.groupby("weak_element")["gap"].median()


def at_risk(history: pd.DataFrame, seasons: pd.DataFrame, moment: Any, config: tiers.TierConfig | None = None,
            rates: pd.DataFrame | None = None, life: pd.DataFrame | None = None) -> pd.DataFrame:
    """The units in use at ``moment`` by the chance their next own-element season passes them by.

    For each unit not retired, its latest own-element season: if it was fielded
    there, the stop rate of its tier there (``rates``, from ``own_outlook``).
    If not, either it sat that season out after its last use (``missed``) and
    retires once it has gone unused long enough (``idle_days``, from its
    lifespan), or other elements' decks fielded it since (``elsewhere``) - a
    season of its own element passing it by again retires it once it is idle.
    ``wait_days`` is the median gap between seasons of that weakness."""
    config = config or tiers.TierConfig()
    rates = stop_rates(own_outlook(history, seasons, config)) if rates is None else rates
    life = tiers.lifespans(history, seasons, moment, config) if life is None else life
    active = set(life.loc[~life["retired"] & life["first_used"].notna(), "unit_id"])
    rows = _counted_rows(history, seasons, moment, config)
    own = rows[rows["own"] & rows["unit_id"].isin(active)].groupby("unit_id").tail(1)
    gaps = rotation_gaps(seasons)
    out = own[["unit_id", "season", "weak_element", "lift", "used", "live"]].rename(columns={"season": "last_own"})
    out["tier"] = out["lift"].map(lambda v: outlook_tier(v, config))
    out["risk"] = out["tier"].map(rates["rate"]).where(out["used"])
    lives = life.set_index("unit_id")
    out["idle_days"] = out["unit_id"].map(lives["idle_days"])
    later = out["unit_id"].map(lives["last_used"]).astype(float) > out["last_own"]
    out["missed"] = ~out["used"] & ~out["live"] & ~later
    out["elsewhere"] = ~out["used"] & ~out["live"] & later
    out["wait_days"] = out["weak_element"].map(gaps)
    return out.sort_values(["risk", "lift"], ascending=[False, True], na_position="last").reset_index(drop=True)


# --------------------------------------------------------------------------
# the study: season by season
# --------------------------------------------------------------------------

def moments(seasons: pd.DataFrame) -> dict[int, pd.Timestamp]:
    """Each season's end - or, in progress, how far it was collected: the moments to replay."""
    out = {}
    for _, row in seasons.sort_values("season").iterrows():
        moment = row["end_at"] if bool(row["final"]) else row["collected_until"]
        if not pd.isna(moment):
            out[int(row["season"])] = moment
    return out


def replay(history: pd.DataFrame, seasons: pd.DataFrame, config: tiers.TierConfig,
           treasured: Callable[[pd.Timestamp], Any] | None = None) -> pd.DataFrame:
    """Where every unit stood at the end of every season: its overall tier, generality and lifespan."""
    parts = []
    for season, moment in moments(seasons).items():
        standing = tiers.standings(history, seasons, moment, config,
                                   treasured=treasured(moment) if treasured else None)
        if standing.overall.empty:
            continue
        frame = (standing.overall[["unit_id", "overall", "overall_tier", "provisional"]]
                 .merge(tiers.generality(standing, config), on="unit_id", how="left")
                 .merge(tiers.lifespans(history, seasons, moment, config), on="unit_id", how="left"))
        parts.append(frame.assign(season=season, moment=moment))
    return pd.concat(parts, ignore_index=True)


def _used_matrix(history: pd.DataFrame, config: tiers.TierConfig) -> pd.DataFrame:
    """Unit x season: fielded there (``tiers.fielded``); False before its release too."""
    used = history.assign(used=tiers.fielded(history, config)).pivot(index="unit_id", columns="season", values="used")
    return used.eq(True)


def by_usage(history: pd.DataFrame, share: float = USAGE_RULE) -> pd.DataFrame:
    """The season table as the lifespan rule saw it before the season tier: a lift of 1 where
    ``share`` of the rankers fielded the unit, 0 elsewhere - fielded or not by usage alone."""
    return history.assign(lift=(history["usage_rate"] >= share).astype(float))


def score_rule(flags: pd.DataFrame, used: pd.DataFrame, *, horizon: int, done_by: int) -> dict[str, Any]:
    """How a retirement rule fared: ``flags`` has ``unit_id``, ``season``, ``retired`` per season's end.

    ``calls``: units it retired by season ``horizon`` (each time it did);
    ``wrong``: those fielded again later. ``done``: units last fielded by
    ``done_by`` and never since - of those, how many it retired, and how many
    seasons after the last use (``delay``)."""
    flags = flags.sort_values(["unit_id", "season"])
    before = flags.groupby("unit_id")["retired"].shift(1, fill_value=False).astype(bool)
    calls = flags[flags["retired"] & ~before & (flags["season"] <= horizon)]
    seasons = list(used.columns)
    later = [bool(used.loc[u, [s for s in seasons if s > season]].any()) for u, season in zip(calls["unit_id"], calls["season"])]
    last = used.apply(lambda row: max((s for s in seasons if row[s]), default=np.nan), axis=1)
    done = last[last <= done_by]
    retired = flags[flags["retired"]]
    first = {u: retired.loc[(retired["unit_id"] == u) & (retired["season"] > done[u]), "season"].min() for u in done.index}
    delays = pd.Series({u: first[u] - done[u] for u in done.index}).dropna()
    newest = flags["season"].max()
    return {"calls": len(calls), "wrong": int(sum(later)), "precision": 1 - (sum(later) / len(calls)) if len(calls) else np.nan,
            "done": len(done), "caught": len(delays), "delay": float(delays.median()) if len(delays) else np.nan,
            "retired_now": int(flags.loc[flags["season"] == newest, "retired"].sum())}


def retirement_rules(history: pd.DataFrame, seasons: pd.DataFrame, config: tiers.TierConfig, panel: pd.DataFrame,
                     *, horizon: int | None = None, done_by: int | None = None) -> pd.DataFrame:
    """The lifespan rule against the rule it replaced and rules read off the element and overall
    tiers, replayed season by season (``panel``, from ``replay``).

    Scored on what happened after (``score_rule``); ``horizon`` defaults to
    eight seasons before the newest, ``done_by`` to eleven."""
    newest = int(panel["season"].max())
    horizon = newest - 8 if horizon is None else horizon
    done_by = newest - 11 if done_by is None else done_by
    used = _used_matrix(history, config)
    old = by_usage(history)
    before = pd.concat([tiers.lifespans(old, seasons, moment, config).assign(season=season)
                        for season, moment in moments(seasons).items()])
    panel = panel.merge(before[["unit_id", "season", "retired"]].rename(columns={"retired": "by_usage"}),
                        on=["unit_id", "season"], how="left")
    now = _true(panel["retired"])
    ever = panel["first_used"].notna()
    f_below = config.overall_cut("D")  # an overall under the D cut is F
    d_below = config.overall_cut("C")  # under the C cut, D or F
    peak = panel.sort_values("season").groupby("unit_id")["overall"].cummax()
    rules = {
        f"지금 규칙 (시즌 티어 {config.min_tier} 이상)": now,
        f"예전 규칙 (사용률 {USAGE_RULE:.0%})": _true(panel["by_usage"]),
        "종합 티어 F": ever & (panel["overall"] < f_below),
        "종합 티어 D 이하": ever & (panel["overall"] < d_below),
        "종합이 전성기의 25% 이하": ever & (panel["overall"] <= 0.25 * peak) & (peak >= d_below),
        "지금 규칙 + 종합 D 이하": now & (panel["overall"] < d_below),
    }
    out = [{"rule": name, **score_rule(panel.assign(retired=flag)[["unit_id", "season", "retired"]], used,
                                        horizon=horizon, done_by=done_by)} for name, flag in rules.items()]
    return pd.DataFrame(out)


# --------------------------------------------------------------------------
# then and now
# --------------------------------------------------------------------------

def eras_of(seasons: Any, size: int = 10) -> dict[int, str]:
    """Seasons in blocks of ``size`` from season 1 ("S1-10", "S11-20", ...); a last block
    of fewer than half that joins the one before ("S31-41")."""
    numbers = sorted({int(s) for s in seasons})
    last = numbers[-1] if numbers else 0
    tail = (last - 1) // size * size + 1  # the first season of the last block
    if last - tail + 1 < size / 2 and tail > 1:
        tail -= size
    out = {}
    for s in numbers:
        first = min((s - 1) // size * size + 1, tail)
        out[s] = f"S{first}-{last if first == tail else first + size - 1}"
    return out


def eras(history: pd.DataFrame, panel: pd.DataFrame, config: tiers.TierConfig) -> pd.DataFrame:
    """Old and recent Solo Raid, ten seasons at a time.

    Where the damage came from (``own_share``: the share of the season's lift
    from units of the boss's weak element), how general the units in use were
    (``generalist``: the share of B-or-better, settled, unretired units in the
    generalist band; ``g_median``), and how well a standing held: of
    the units at A or better in a season, how many were A or better again in
    the next season of the same boss weakness, their own element's
    (``keep_own``) or another (``keep_other``); and of the units at overall A
    or better, how many still were ten seasons on (``keep_overall_10``). By the
    era a unit was first fielded in, of the units that ever reached a season
    tier of A and have been around a year since: how many retired within that
    year (``retired_in_year``, of ``debuts``)."""
    rows = history.assign(own=_flags(history, "element_match"))
    total = rows.groupby("season")["lift"].transform("sum")
    rows["share"] = rows["lift"] / total
    per_season = pd.DataFrame({"own_share": rows["share"].where(rows["own"], 0.0).groupby(rows["season"]).sum()})
    era = eras_of(rows["season"]).get
    frame = per_season.groupby(per_season.index.map(era)).mean()

    live = panel[(panel["overall"] >= config.overall_cut("B")) & ~_true(panel["provisional"]) & ~_true(panel["retired"])
                 & panel["generality"].notna()]
    frame["generalist"] = (live["generality_band"] == "generalist").groupby(live["season"].map(era)).mean()
    frame["g_median"] = live.groupby(live["season"].map(era))["generality"].median()

    a = config.cut("A")
    same = rows.sort_values("season")
    following = same.groupby(["unit_id", "weak_element"])
    same = same.assign(next_lift=following["lift"].shift(-1), next_season=following["season"].shift(-1))
    final = set(history.loc[_flags(history, "final"), "season"])
    same = same[(same["lift"] >= a) & same["next_season"].isin(final)]
    kept = same["next_lift"] >= a
    for side, mask in (("keep_own", same["own"]), ("keep_other", ~same["own"])):
        frame[side] = kept[mask].groupby(same.loc[mask, "season"].map(era)).mean()

    overall_a = config.overall_cut("A")
    ahead = panel.sort_values("season")
    ahead = ahead.assign(later=ahead.groupby("unit_id")["overall"].shift(-10))
    ahead = ahead[(ahead["overall"] >= overall_a) & ~_true(ahead["provisional"]) & ahead["later"].notna()]
    frame["keep_overall_10"] = (ahead["later"] >= overall_a).groupby(ahead["season"].map(era)).mean()

    views = panel.drop_duplicates("season").set_index("season")["moment"]
    start = history.drop_duplicates("season").set_index("season")["start_at"].map(pd.Timestamp)
    reached = rows.groupby("unit_id")["lift"].max() >= a
    newest = panel.loc[panel["season"] == panel["season"].max()].set_index("unit_id")
    debut = newest["first_used"].dropna().astype(int)
    debut = debut[debut.index.map(reached).fillna(False).astype(bool)]
    retired = panel[_true(panel["retired"])].groupby("unit_id")["season"].min().map(views)
    year = pd.Timedelta(days=365)
    began = debut.map(start)
    followed = began + year <= views.max()
    within = (retired.reindex(debut.index) - began <= year).fillna(False)
    frame["retired_in_year"] = within[followed].groupby(debut[followed].map(era)).mean()
    frame["debuts"] = debut[followed].groupby(debut[followed].map(era)).size()
    return frame


# --------------------------------------------------------------------------
# which way a career went
# --------------------------------------------------------------------------

LEFT_AFTER = 3  # other-element seasons in a row without it: it has left them
CAREER_COLUMNS = ["unit_id", "other_used", "last_other", "other_since", "own_after", "path"]
PATHS = ("generalist", "element_only", "left_others", "specialist",
         "retired_generalist", "retired_element_only", "retired_specialist", "unused")
PATH_KO = {"generalist": "범용", "element_only": "속성 전용", "left_others": "다른 속성에서 빠짐", "specialist": "특화",
           "retired_generalist": "범용 → 은퇴", "retired_element_only": "범용 → 속성 전용 → 은퇴",
           "retired_specialist": "특화 → 은퇴", "unused": "안 쓰임"}


def careers(table: pd.DataFrame, seasons: pd.DataFrame, moment: Any, config: tiers.TierConfig | None = None,
            life: pd.DataFrame | None = None, left_after: int = LEFT_AFTER) -> pd.DataFrame:
    """Which way each unit's career went, as known at ``moment`` - one row per unit out by then.

    Same seasons and same *fielded* as ``tiers.lifespans`` (``life``, its result
    at ``moment``, computed when not given). Per unit: the seasons of other
    elements' weakness that fielded it (``other_used``), the latest
    (``last_other``), the other-element seasons since (``other_since``), and its
    own element's seasons that fielded it after that (``own_after``; all of them
    when no other-element season did). Its ``path``:

    * ``generalist`` - fielded in an other-element season, and in one of its
      latest ``left_after``;
    * ``element_only`` - a generalist once, not fielded in its latest
      ``left_after`` other-element seasons, fielded in its own since;
    * ``left_others`` - the same, with no own-element season fielding it since
      (none may have come round yet);
    * ``specialist`` - never fielded in an other-element season (a new unit
      too, until it is);
    * ``retired_generalist`` / ``retired_element_only`` - retired straight from
      general use, or after fielded only in its own element's seasons for a
      while; ``retired_specialist`` - retired, never a generalist;
    * ``unused`` - no season fielded it.
    """
    config = config or tiers.TierConfig()
    counted = tiers.counted_seasons(seasons, moment, config)
    if counted.empty or table.empty:
        return pd.DataFrame(columns=CAREER_COLUMNS)
    rows = table.loc[table["season"].isin(counted["season"])]
    rows = (rows.assign(used=tiers.fielded(rows, config), own=_flags(rows, "element_match"))[["season", "unit_id", "used", "own"]]
            .sort_values(["unit_id", "season"]))
    life = tiers.lifespans(table, seasons, moment, config) if life is None else life
    retired = life.set_index("unit_id")["retired"]
    out = []
    for unit_id, group in rows.groupby("unit_id", sort=True):
        other, own = group[~group["own"]], group[group["own"]]
        other_used = other.loc[other["used"], "season"]
        last_other = int(other_used.max()) if len(other_used) else None
        after = (lambda frame: frame) if last_other is None else (lambda frame: frame[frame["season"] > last_other])
        record = {"unit_id": unit_id, "other_used": len(other_used), "last_other": last_other,
                  "other_since": len(after(other)), "own_after": int(after(own)["used"].sum())}
        general = record["other_used"] > 0
        if not group["used"].any():
            path = "unused"
        elif bool(retired.get(unit_id, False)):
            path = ("retired_element_only" if record["own_after"] else "retired_generalist") if general \
                else "retired_specialist"
        elif not general:
            path = "specialist"
        elif record["other_since"] < left_after:
            path = "generalist"
        else:
            path = "element_only" if record["own_after"] else "left_others"
        out.append({**record, "path": path})
    frame = pd.DataFrame(out, columns=CAREER_COLUMNS)
    frame["last_other"] = frame["last_other"].astype("Int64")
    return frame


# --------------------------------------------------------------------------
# the shape of a whole career
# --------------------------------------------------------------------------

ROTATION_COLUMNS = ["unit_id", "rotation", "own_season", "own", "other", "others", "level", "generality"]
CURVE_WIDE = 0.5  # generality at its peak from here: it started out general
CURVES = ("unused", "specialist", "narrowed", "faded", "general", "unknown")
CURVE_KO = {"unused": "안 쓰임", "specialist": "처음부터 속성 전용", "narrowed": "범용 → 속성 전용",
            "faded": "범용인 채로 저묾", "general": "아직 범용", "unknown": "아직 모름"}


def rotations(table: pd.DataFrame) -> pd.DataFrame:
    """Each unit's career one turn of the element rotation at a time.

    A turn is a season of the unit's own element (``own_season``) and the
    other-element seasons after it, up to the next own-element season; the
    first also takes the other-element seasons before it, and own-element
    seasons back to back share a turn. Per turn: its lift in the own-element
    season(s) (``own``, their mean), the mean of the others (``other``, over
    ``others`` seasons), ``level = (own + other) / 2`` and ``generality =
    2 x other / (own + other)`` - the tiers' generality, on the seasons of
    the turn alone, without the tiers' memory."""
    rows = table.assign(own=_flags(table, "element_match")).sort_values(["unit_id", "season"])
    out = []
    for unit_id, group in rows.groupby("unit_id", sort=True):
        own = group["own"].to_numpy(dtype=bool)
        if not own.any():
            continue
        lift, season = group["lift"].to_numpy(dtype=float), group["season"].to_numpy()
        turn = np.maximum(np.cumsum(own) - 1, 0)  # the others before the first own season join the first turn
        starts = np.flatnonzero(own)
        # own seasons back to back: the later joins the turn before
        merged = np.cumsum(np.r_[True, ~(np.diff(starts) == 1)]) - 1
        turn = merged[turn]
        for k in np.unique(turn):
            here = turn == k
            mine, rest = lift[here & own], lift[here & ~own]
            out.append({"unit_id": unit_id, "rotation": int(k), "own_season": int(season[here & own][0]),
                        "own": float(mine.mean()), "other": float(rest.mean()) if len(rest) else np.nan,
                        "others": int(len(rest))})
    frame = pd.DataFrame(out, columns=ROTATION_COLUMNS[:-2])
    total = frame["own"] + frame["other"]
    frame["level"] = total / 2
    frame["generality"] = (2 * frame["other"] / total).where(total > 0)
    return frame[ROTATION_COLUMNS]


def curves(table: pd.DataFrame, config: tiers.TierConfig | None = None, *, wide: float = CURVE_WIDE) -> pd.DataFrame:
    """The shape of each unit's career from its turns of the rotation (``rotations``).

    Per unit: its best turn's ``level`` (``peak``); its generality at the top
    (``g_peak``: the turns up to the best one at half its level or more,
    weighted by level); the lowest generality after the best turn while still
    in use (``g_low``: a turn with ``own`` or ``other`` at the C cut or more);
    ``narrow_turns``, those in-use turns with ``other`` under a quarter of
    ``own``; and whether it has come down (``declined``: its latest turn under
    half the peak). Its ``curve``:

    * ``unused`` - no turn reached the C cut;
    * ``specialist`` - narrow from the start (``g_peak`` under ``wide``);
    * ``narrowed`` - general at the top, then used in its own element's
      seasons only (``g_low`` under the lower generality band);
    * ``faded`` - general at the top and came down still general;
    * ``general`` - general and not come down yet: which of the two it ends
      as, the data does not say yet;
    * ``unknown`` - fewer than two turns, or no other-element season yet.
    """
    config = config or tiers.TierConfig()
    use, narrow = config.cut("C"), config.generality_bands[0]
    out = []
    for unit_id, turns in rotations(table).groupby("unit_id", sort=True):
        level, g = turns["level"].to_numpy(), turns["generality"].to_numpy()
        own, other = turns["own"].to_numpy(), turns["other"].fillna(0).to_numpy()
        top = int(np.nanargmax(np.nan_to_num(level, nan=own / 2)))
        peak = float(np.nanmax(np.nan_to_num(level, nan=own / 2)))
        rise = [i for i in range(top + 1) if level[i] >= peak / 2 and level[i] > 0]
        g_peak = float(np.average(g[rise], weights=level[rise])) if rise else np.nan
        after = [i for i in range(top, len(turns)) if (own[i] >= use or other[i] >= use) and not np.isnan(g[i])]
        g_low = float(np.nanmin(g[after])) if after else np.nan
        declined = len(turns) > 1 and np.nan_to_num(level[-1], nan=own[-1] / 2) < peak / 2
        if len(turns) < 2 or np.isnan(g_peak):
            curve = "unused" if len(turns) >= 2 and peak < use else "unknown"
        elif peak < use:
            curve = "unused"
        elif g_peak < wide:
            curve = "specialist"
        elif g_low < narrow:
            curve = "narrowed"
        else:
            curve = "faded" if declined else "general"
        out.append({"unit_id": unit_id, "turns": len(turns), "peak": peak, "g_peak": g_peak, "g_low": g_low,
                    "narrow_turns": sum(1 for i in after if other[i] < own[i] / 4), "declined": bool(declined),
                    "curve": curve})
    return pd.DataFrame(out)


# --------------------------------------------------------------------------
# the meta: following the boss's weakness
# --------------------------------------------------------------------------

def _cross_weakness(lifts: pd.DataFrame, weak: pd.Series, back: int = 4) -> pd.Series:
    """Per season, how alike its lifts (unit x season) are to those of the last ``back`` seasons
    of another boss weakness: the mean cosine. 1 = the same units whatever the weakness."""
    out = {}
    for season in lifts.columns:
        before = [s for s in lifts.columns if s < season and weak[s] != weak[season]][-back:]
        if len(before) < back:
            continue
        now = lifts[season].to_numpy()
        out[season] = float(np.mean([now @ lifts[s].to_numpy() / (np.linalg.norm(now) * np.linalg.norm(lifts[s]))
                                     for s in before]))
    return pd.Series(out, dtype=float)


def usage_mix(history: pd.DataFrame, config: tiers.TierConfig | None = None, days: int = 365) -> pd.DataFrame:
    """Per season, the units in use over the ``days`` up to its start, by how general they were
    then - with no memory beyond that window.

    Per unit, over the seasons that started in the window: the mean lift in
    its own element's seasons (O) and in the others (X), and ``2X / (O + X)``;
    a unit counts when it met both sides in the window and either mean is at
    the C cut or more. ``specialist`` / ``element_first`` / ``generalist``:
    how many fall in each generality band, ``units`` all of them."""
    config = config or tiers.TierConfig()
    rows = history.assign(own=_flags(history, "element_match"), start=pd.to_datetime(history["start_at"], utc=True))
    starts = rows.drop_duplicates("season").set_index("season")["start"].sort_index()
    use, (low, high) = config.cut("C"), config.generality_bands
    out = []
    for season, begun in starts.items():
        window = rows[(rows["start"] > begun - pd.Timedelta(days=days)) & (rows["start"] <= begun)]
        sides = window.groupby(["unit_id", "own"])["lift"].mean().unstack().reindex(columns=[True, False]).dropna()
        sides = sides[(sides[True] >= use) | (sides[False] >= use)]
        g = 2 * sides[False] / (sides[True] + sides[False])
        out.append({"season": season, "units": len(g), "specialist": int((g < low).sum()),
                    "element_first": int(((g >= low) & (g < high)).sum()), "generalist": int((g >= high).sum())})
    return pd.DataFrame(out).set_index("season")


def meta_index(history: pd.DataFrame, config: tiers.TierConfig | None = None) -> pd.DataFrame:
    """Per season, how far the units in use depend on the boss's weakness.

    ``same``: how alike the season's lifts are to those of the four seasons
    before it of another weakness (``_cross_weakness``); ``own_share``: the
    share of the season's lift from units of the weak element; ``good_own`` /
    ``good_other``: units at a season tier of B or better, of the weak element
    or not; ``pool``: units of the weak element out by then."""
    config = config or tiers.TierConfig()
    rows = history.assign(own=_flags(history, "element_match"))
    weak = rows.drop_duplicates("season").set_index("season")["weak_element"]
    total = rows.groupby("season")["lift"].transform("sum")
    frame = pd.DataFrame(index=sorted(rows["season"].unique()))
    lifts = rows.pivot_table(index="unit_id", columns="season", values="lift", fill_value=0)
    frame["same"] = _cross_weakness(lifts, weak)
    frame["own_share"] = (rows["lift"] / total).where(rows["own"], 0.0).groupby(rows["season"]).sum()
    good = rows["lift"] >= config.cut("B")
    for name, mask in (("good_own", rows["own"] & good), ("good_other", ~rows["own"] & good), ("pool", rows["own"])):
        frame[name] = mask.groupby(rows["season"]).sum()
    return frame.rename_axis("season")


def debuts(history: pd.DataFrame, config: tiers.TierConfig | None = None) -> pd.DataFrame:
    """Each unit that reached a season tier of A: how it was used in its first year from its
    first season in use - the mean lift in its own element's seasons (``own``) and in the others
    (``other``), their ``generality`` - and the season it came in (``first``)."""
    config = config or tiers.TierConfig()
    rows = history.assign(own=_flags(history, "element_match"), start=pd.to_datetime(history["start_at"], utc=True),
                          used=tiers.fielded(history, config)).sort_values("season")
    out = []
    for unit_id, group in rows.groupby("unit_id"):
        if group["lift"].max() < config.cut("A") or not group["used"].any():
            continue
        began = group.loc[group["used"], "start"].iloc[0]
        year = group[(group["start"] >= began) & (group["start"] < began + pd.Timedelta(days=365))]
        own, other = year.loc[year["own"], "lift"].mean(), year.loc[~year["own"], "lift"].mean()
        out.append({"unit_id": unit_id, "first": int(group.loc[group["used"], "season"].iloc[0]),
                    "own": own, "other": other,
                    "generality": 2 * other / (own + other) if own + other > 0 else np.nan,
                    "year_over": bool(began + pd.Timedelta(days=365) <= rows["start"].max())})
    return pd.DataFrame(out)


# --------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------

def _pct(value: float) -> str:
    return "-" if pd.isna(value) else f"{value * 100:.0f}%"


def report(book=None) -> str:
    """The numbers in docs/lifecycle.md, from the committed tables."""
    from .tierlist import GENERALITY_KO, TierBook

    book = book or TierBook.load()
    history, seasons, config = book.history, book.seasons, book.config
    names = history.drop_duplicates("unit_id").set_index("unit_id")
    label = names["name_ko"].where(names["name_ko"].fillna("") != "", names["name_en"])
    panel = replay(history, seasons, config, treasured=book.treasured)
    newest = int(panel["season"].max())
    now = moments(seasons)[newest]
    life = tiers.lifespans(history, seasons, now, config)
    lines = [f"시즌 1-{newest} 기준 (진행 중 시즌은 수집분까지)", ""]

    lines.append("1. 은퇴를 티어로: 규칙마다 시즌별로 다시 돌려 본 결과")
    rules = retirement_rules(history, seasons, config, panel)
    lines.append(f"   은퇴 판정 = 시즌 {newest - 8}까지 내린 은퇴 판정 · 틀림 = 그 뒤 다시 쓰임 · "
                 f"끝난 니케 = 시즌 {newest - 11}까지 쓰이고 그 뒤로 안 쓰인 니케")
    for r in rules.itertuples():
        lines.append(f"   {r.rule:<24} 판정 {r.calls:>3} · 틀림 {r.wrong:>2} ({_pct(1 - r.precision)}) · "
                     f"끝난 니케 {r.caught}/{r.done} 잡음, 마지막 사용 뒤 {r.delay:.0f}시즌 · 지금 은퇴 {r.retired_now}")
    retired_now = panel[(panel["season"] == newest) & _true(panel["retired"])]
    counts = retired_now["overall_tier"].value_counts().reindex(config.tier_order).dropna().astype(int)
    lines.append("   지금 은퇴한 니케의 종합 티어: " + " · ".join(f"{k} {v}" for k, v in counts.items()))
    same = (history["usage_rate"] >= USAGE_RULE) == tiers.fielded(history, config)
    lines.append(f"   시즌마다 '사용률 {USAGE_RULE:.0%} 이상'과 '시즌 티어 {config.min_tier} 이상'이 같게 가른 비율: "
                 f"{_pct(same.mean())} ({int(same.sum())}/{len(same)})")
    lines.append("")

    lines.append("2. 범용도 g = 2X / (O + X) — O 자기 속성 칸(속성 티어), X 다른 속성 칸 평균. "
                 "1 = 약점과 무관, 2 = 다른 속성 시즌에만 쓰임")
    here = panel[(panel["season"] == newest) & panel["generality"].notna() & ~_true(panel["retired"])]
    here = here.assign(name=here["unit_id"].map(label)).sort_values("generality")
    for band, group in here.groupby("generality_band", sort=False):
        units = " · ".join(f"{r.name} {r.generality:.2f}" for r in group.itertuples())
        lines.append(f"   {GENERALITY_KO[band]} ({len(group)}명): {units}")
    lines.append("")

    lines.append("3. 범용이던 니케의 길 (다른 속성 시즌에 쓰인 적 있는 니케)")
    paths = careers(history, seasons, now, config, life)
    general = paths[paths["other_used"] > 0]
    for path in [p for p in PATHS if p in set(general["path"])]:
        members = general[general["path"] == path]
        lines.append(f"   {PATH_KO[path]:<18} {len(members):>3}명  — " + ", ".join(members["unit_id"].map(label)))
    ended = general[general["path"].isin(["element_only", "retired_element_only", "retired_generalist"])]
    went = ended["path"] != "retired_generalist"
    lines.append(f"   범용을 끝낸 니케: {_pct(went.mean())}가 속성 전용을 거쳤다 ({int(went.sum())}/{len(went)})")
    lines.append("")

    lines.append("4. 예전과 요즘 (10시즌씩)")
    table = eras(history, panel, config)
    lines.append("   구간      약점 속성 니케의 기여도 몫 | "
                 "범용 비율 · g 중앙값 | A 유지(다음 같은 약점): 자기 속성 · 다른 속성 | 종합 A 10시즌 뒤 | "
                 "1년 안 은퇴(이 구간에 데뷔, 시즌 A 이상 찍은 니케)")
    for name, r in table.iterrows():
        lines.append(f"   {name:<8}  {_pct(r.own_share):>4} | {_pct(r.generalist):>4} · {r.g_median:.2f} | "
                     f"{_pct(r.keep_own):>4} · {_pct(r.keep_other):>4} | {_pct(r.keep_overall_10):>4} | "
                     f"{_pct(r.retired_in_year)}" + (f" ({r.debuts:.0f}명)" if r.debuts == r.debuts else ""))
    lines.append("")

    lines.append("5. 자기 속성 시즌에 쓰였을 때, 다음 자기 속성 시즌에 안 쓰일 확률 (그 시즌의 시즌 티어별)")
    outlook = own_outlook(history, seasons, config)
    rates = stop_rates(outlook)
    lines.append("   " + " · ".join(f"{tier} {_pct(r.rate)} (n={int(r.n)})" for tier, r in rates.iterrows()))
    split = newest * 2 // 3
    before, after = outlook[outlook["season"] <= split], outlook[outlook["season"] > split]
    fitted, held = stop_rates(before), stop_rates(after)
    lines.append(f"   시즌 {split}까지로 잰 확률 → 그 뒤에서 본 확률: " + " · ".join(
        f"{tier} {_pct(fitted.loc[tier, 'rate'])} → {_pct(held.loc[tier, 'rate'])}" for tier in held.index))
    guess = after["tier"].map(fitted["rate"]).astype(float)
    flat = before["stopped"].mean()
    lines.append(f"   그 뒤 {len(after)}번에 대한 브라이어 점수: 티어별 {((guess - after['stopped']) ** 2).mean():.3f} · "
                 f"티어 무시 {((flat - after['stopped']) ** 2).mean():.3f} (낮을수록 좋음)")
    gaps = rotation_gaps(seasons)
    lines.append("   같은 약점이 돌아오는 간격(중앙값): " + " · ".join(f"{e} {gaps[e]:.0f}일" for e in ELEMENTS if e in gaps))
    risky = at_risk(history, seasons, now, config, rates, life)
    risky = risky[(risky["risk"] >= 0.3) | risky["missed"] | risky["elsewhere"]]
    phase = paths.set_index("unit_id")["path"].map(PATH_KO)
    for r in risky.itertuples():
        if r.missed:
            state = f"마지막으로 쓰인 뒤 그 시즌도 놓쳤고 {r.idle_days:.0f}일째 안 쓰임"
        elif r.elsewhere:
            state = "그 시즌엔 안 쓰였고 그 뒤 다른 속성 덱에서 쓰임"
        else:
            state = f"다음 자기 속성 시즌에 안 쓰일 확률 {_pct(r.risk)}"
        lines.append(f"   {label[r.unit_id]:<16} {phase.get(r.unit_id, ''):<8} 마지막 자기 속성 시즌 {r.last_own} "
                     f"{r.tier} {r.lift:.2f} → {state} (보통 {r.wait_days:.0f}일 간격)")
    lines.append("")

    lines.append(f"6. 생애 곡선 (로테이션 한 바퀴 = 자기 속성 시즌 하나와 그 뒤 다른 속성 시즌들, 쓰임 = 시즌 티어 C 이상, "
                 f"처음부터 범용 = 전성기 범용도 {CURVE_WIDE} 이상, 속성 전용으로 좁아짐 = 범용도 "
                 f"{config.generality_bands[0]} 아래)")
    shapes = curves(history, config).assign(name=lambda f: f["unit_id"].map(label))
    for curve in CURVES:
        members = shapes[shapes["curve"] == curve]
        listed = ", ".join(members.sort_values("peak", ascending=False)["name"].head(12))
        lines.append(f"   {CURVE_KO[curve]:<12} {len(members):>3}명  — {listed}")
    ended = shapes[shapes["curve"].isin(["narrowed", "faded"])]
    lines.append("   범용 → 속성 전용 · 범용인 채로 저묾의 전성기 범용도 중앙값: " + " · ".join(
        f"{CURVE_KO[c]} {ended.loc[ended['curve'] == c, 'g_peak'].median():.2f}" for c in ("narrowed", "faded")))
    lines.append("")

    lines.append("7. 메타: 약점을 따르는 정도 (10시즌씩)")
    meta = meta_index(history, config)
    era = eras_of(history["season"])
    block = meta.groupby(meta.index.map(era)).mean()
    lines.append("   구간      약점 교차 유사도 | 약점 속성 니케의 몫 | 시즌 B 이상: 약점 속성 · 다른 속성 | 약점 속성 니케 풀")
    for name, r in block.iterrows():
        lines.append(f"   {name:<8}  {r.same:.2f} | {_pct(r.own_share):>4} | {r.good_own:.1f} · {r.good_other:.1f} | "
                     f"{r.pool:.1f}")
    mix = usage_mix(history, config)
    lines.append("   그 시즌까지 1년 동안 쓰인 니케(C 이상), 그 1년의 범용도로: 특화 · 속성 우선 · 범용 / 전체 (특화 비율)")
    lines.append("   " + " | ".join(f"S{i} {r.specialist} · {r.element_first} · {r.generalist} / {r.units} "
                                    f"({_pct(r.specialist / r.units)})" for i, r in mix.loc[mix.index % 5 == 1].iloc[1:].iterrows()))
    lines.append("   시즌별 약점 교차 유사도: " + " ".join(f"{s}:{v:.2f}" for s, v in meta["same"].dropna().items()))
    first = debuts(history, config)
    first = first.assign(era=first["first"].map(era))
    lines.append("   시즌 A 이상을 찍은 니케의 첫 1년 (데뷔 구간별): 범용도 중앙값 · 범용도 0.7 이상 비율 · "
                 "자기 속성 시즌 기여도 중앙값 · 명")
    lines.append("   " + " | ".join(
        f"{e} {g['generality'].median():.2f} · {_pct((g['generality'] >= 0.7).mean())} · {g['own'].median():.2f} · "
        f"{len(g)}" for e, g in first.groupby("era")))
    return "\n".join(lines)


if __name__ == "__main__":
    print(report())
