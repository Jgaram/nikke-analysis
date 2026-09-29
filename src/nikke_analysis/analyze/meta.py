"""How the meta moved: season by season, how far the units in use follow the boss's weakness.

The tier site's 메타 변화 tab shows these, computed in the browser
(``web/js/model.js`` follows this module as it follows ``metrics.py`` and
``tiers.py``; tests/test_web.py holds the two against each other).

**Generality mix** (``usage_mix``): per season, the units in use over the
``meta_window_days`` up to its start, banded by the generality of that window
alone - no memory beyond it. A window rather than one season because a unit's
own element comes round only every few months: a year holds every element.

**Weakness similarity** (``weakness_similarity``): how alike a season's lifts
are to those of the seasons before it with another weakness - 1 when the same
units carry whatever the weakness, 0 when every weakness has its own.

**Own-element share** (``own_share``): the share of a season's lift that went to
units of the boss's weak element (a fifth when the weakness made no
difference).

**Debuts** (``debuts``): each unit's first year from its first season in use,
and how general it was over it.

None of it is a role: a unit fielded in its own element's seasons only may deal
the damage there or give that element's decks what they need.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .tiers import TierConfig, fielded, flags, generality_band

SIMILARITY_BACK = 4  # seasons of another weakness each season is held against: the other four
MIX_COLUMNS = ["units", "specialist", "element_first", "generalist"]
DEBUT_COLUMNS = ["unit_id", "first", "own", "other", "generality"]


def _rows(table: pd.DataFrame, seasons: pd.DataFrame) -> pd.DataFrame:
    rows = table[["season", "unit_id", "lift"]].assign(own=flags(table, "element_match"))
    starts = seasons.set_index("season")["start_at"].map(lambda v: pd.Timestamp(v)).map(
        lambda t: t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC"))
    return rows.assign(start=rows["season"].map(starts))


def _mix(rows: pd.DataFrame, config: TierConfig) -> dict[str, int]:
    """Units in ``rows`` (a window) that met both sides with either mean at ``curve_min_tier``
    or better, by generality band."""
    sides = rows.groupby(["unit_id", "own"])["lift"].mean().unstack()
    sides = sides.reindex(columns=[True, False]).dropna()
    use = config.cut(config.curve_min_tier)
    sides = sides[(sides[True] >= use) | (sides[False] >= use)]
    bands = (2 * sides[False] / (sides[True] + sides[False])).map(lambda g: generality_band(g, config))
    return {"units": len(bands), **{band: int((bands == band).sum()) for band in MIX_COLUMNS[1:]}}


def usage_mix(table: pd.DataFrame, seasons: pd.DataFrame, config: TierConfig | None = None) -> pd.DataFrame:
    """Per season with a start, the units in use over the ``meta_window_days`` up to its
    start (the seasons that started in that span, it included): per unit the mean lift in its
    own element's seasons (O) and in the others (X) there; a unit counts once it met both
    sides and either mean is at ``curve_min_tier`` or better. ``specialist`` /
    ``element_first`` / ``generalist``: how many fall in each generality band of ``2X / (O +
    X)``; ``units``: all of them."""
    config = config or TierConfig()
    rows = _rows(table, seasons).dropna(subset=["start"])
    span = pd.Timedelta(days=config.meta_window_days)
    out = {}
    for season, begun in rows.drop_duplicates("season").set_index("season")["start"].sort_index().items():
        window = rows[(rows["start"] > begun - span) & (rows["start"] <= begun)]
        out[season] = _mix(window, config)
    return pd.DataFrame.from_dict(out, orient="index", columns=MIX_COLUMNS).rename_axis("season")


def weakness_similarity(table: pd.DataFrame, seasons: pd.DataFrame, back: int = SIMILARITY_BACK) -> pd.Series:
    """Per season, the mean cosine similarity of its lifts (one per unit, 0 for a unit it did
    not field) to those of each of the ``back`` latest seasons before it of another boss
    weakness; none until there are that many."""
    weak = seasons.set_index("season")["weak_element"]
    lifts = table.pivot_table(index="unit_id", columns="season", values="lift", aggfunc="sum", fill_value=0.0)
    order = sorted(lifts.columns)
    out = {}
    for season in order:
        before = [s for s in order if s < season and weak.get(s) != weak.get(season)][-back:]
        if len(before) < back:
            continue
        now = lifts[season].to_numpy(dtype=float)
        out[season] = float(np.mean([now @ lifts[s].to_numpy(dtype=float)
                                     / (np.linalg.norm(now) * np.linalg.norm(lifts[s].to_numpy(dtype=float)))
                                     for s in before]))
    return pd.Series(out, dtype=float).rename_axis("season")


def own_share(table: pd.DataFrame) -> pd.Series:
    """Per season, the share of its lift that went to units of the boss's weak element."""
    own = flags(table, "element_match")
    total = table.groupby("season")["lift"].sum()
    return (table["lift"].where(own, 0.0).groupby(table["season"]).sum() / total).rename_axis("season")


def debuts(table: pd.DataFrame, seasons: pd.DataFrame, config: TierConfig | None = None) -> pd.DataFrame:
    """Each unit in use in its first year: from its first season in use (``fielded``), the
    seasons that started within ``meta_window_days`` - its mean lift in its own element's
    seasons (``own``) and in the others (``other``), and ``2 x other / (own + other)``. A unit
    counts once that year is over and either mean is at ``curve_min_tier`` or better; one that
    met only one side has no generality."""
    config = config or TierConfig()
    rows = _rows(table, seasons).dropna(subset=["start"]).assign(used=fielded(table, config))
    newest = rows["start"].max()
    span = pd.Timedelta(days=config.meta_window_days)
    use = config.cut(config.curve_min_tier)
    out = []
    for unit_id, group in rows.sort_values("season").groupby("unit_id", sort=True):
        if not group["used"].any():
            continue
        began = group.loc[group["used"], "start"].iloc[0]
        if began + span > newest:
            continue
        year = group[(group["start"] >= began) & (group["start"] < began + span)]
        own, other = year.loc[year["own"], "lift"].mean(), year.loc[~year["own"], "lift"].mean()
        if not (own >= use or other >= use):
            continue
        g = 2 * other / (own + other) if own + other > 0 else np.nan
        out.append({"unit_id": unit_id, "first": int(group.loc[group["used"], "season"].iloc[0]),
                    "own": own, "other": other, "generality": g})
    return pd.DataFrame(out, columns=DEBUT_COLUMNS)


def trend(table: pd.DataFrame, seasons: pd.DataFrame, config: TierConfig | None = None) -> pd.DataFrame:
    """Per season: ``usage_mix``, ``similarity`` (``weakness_similarity``) and ``own_share``."""
    config = config or TierConfig()
    frame = usage_mix(table, seasons, config)
    frame["similarity"] = weakness_similarity(table, seasons)
    frame["own_share"] = own_share(table)
    return frame
