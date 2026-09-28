"""The measurements that turn Solo Raid leaderboards into a meta.

The data: every season, the top 50 players of each server, each fielding five
decks of five units (every unit at most once), with every deck's damage. A
player's score is the sum of the five decks.

That shape decides what can be measured. Top players converge on almost the same
25 units every season, so "is this unit used" saturates near 100% for the whole
meta roster and cannot rank it. What does separate units is *which deck* they
carry: the main deck does a third of a player's damage, the fifth deck an eighth.

**Credit.** Each player's damage is split over their decks by each deck's share,
and a deck's share equally over its members. A unit's credit in a season is the
rank-weighted average of what it receives, so over all units credit sums to one:
it is the share of the top players' damage that the unit took part in.

**Lift.** Credit times the number of slots a player fields (25). 1.0 is what an
average member of the meta roster carries; a unit in every main deck of a
dominant season reaches about 1.6, a fifth-deck regular about 0.6, a unit
nobody fields 0. Being a share, lift is comparable across seasons however much
damage numbers inflate.

**Rank weighting.** Rank 1 and rank 50 are not equal evidence. Players are
weighted by ``1 / log2(rank + 1)`` within their server (1.00 at rank 1, 0.18 at
rank 50), the discount used in ranking evaluation.

**Availability.** A unit that did not exist during a season did not "fail to be
picked". Season rows cover exactly the units released by the season's start
(plus any unit the data shows was fielded), and every such unit gets a row, zero
if nobody used it - so an unused unit reads as zero, not as missing.

**Deck effect** (a diagnostic, not part of the tier). Comparing a player's five
decks with each other holds the account fixed - its investment, its skill - which
the leaderboard otherwise confounds with unit strength. A ridge regression of log
deck damage on the units in the deck, within each player, estimates how much a
unit raises its deck. It can only separate units that are sometimes swapped for
each other; when every player runs the same five units together, the five share
one estimate.
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

ELEMENTS = ("Fire", "Water", "Wind", "Iron", "Electric")
RANKER_KEYS = ["season", "server", "player"]
DECK_KEYS = RANKER_KEYS + ["deck"]
UNIT_INFO = ["name_ko", "name_en", "element", "burst", "unit_class", "rarity", "release_date"]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def rank_weight(rank: pd.Series | np.ndarray, scheme: str = "dcg") -> np.ndarray:
    """``dcg``: ``1 / log2(rank + 1)``; ``uniform``: every ranked player counts 1."""
    ranks = np.asarray(rank, dtype=float)
    ranks = np.where(ranks < 1, 1.0, ranks)
    if scheme == "uniform":
        return np.ones_like(ranks)
    if scheme != "dcg":
        raise ValueError(f"unknown rank weighting {scheme!r}; use 'dcg' or 'uniform'")
    return 1.0 / np.log2(ranks + 1.0)


def season_order(seasons) -> list[int]:
    return sorted({int(s) for s in seasons})


def season_frame(rows: pd.DataFrame) -> pd.DataFrame:
    """``soloraid_seasons.csv`` as typed columns: instants in UTC, season as int."""
    if rows.empty:
        return pd.DataFrame(columns=["season", "boss_en", "boss_ko", "element", "weak_element", "start_at", "end_at"])
    out = pd.DataFrame(
        {
            "season": pd.to_numeric(rows["season"], errors="coerce"),
            "boss_en": rows.get("boss_en", ""),
            "boss_ko": rows.get("boss_ko", ""),
            "boss_element": rows.get("element", ""),
            "weak_element": rows.get("weak_element", ""),
            "start_at": pd.to_datetime(rows.get("start_at"), errors="coerce", utc=True),
            "end_at": pd.to_datetime(rows.get("end_at"), errors="coerce", utc=True),
        }
    )
    out = out.dropna(subset=["season"])
    out["season"] = out["season"].astype(int)
    return out.sort_values("season").reset_index(drop=True)


def release_instants(roster: pd.DataFrame) -> pd.Series:
    """When each unit became available, UTC. ``release_at`` when known, else the date at 00:00 KST."""
    empty = pd.Series("", index=roster.index)
    at = pd.to_datetime(roster.get("release_at", empty), errors="coerce", utc=True)
    day = pd.to_datetime(roster.get("release_date", empty), errors="coerce")
    day = day.dt.tz_localize("Asia/Seoul").dt.tz_convert("UTC")
    return pd.Series(at.fillna(day).to_numpy(), index=roster["unit_id"].to_numpy())


def select_population(entries: pd.DataFrame, *, top_n: int = 50, servers: tuple[str, ...] = ()) -> pd.DataFrame:
    """The ranked players the metrics are defined on: ranks 1..``top_n`` of the chosen servers."""
    work = entries[(entries["rank"] >= 1) & (entries["rank"] <= top_n)]
    if servers:
        work = work[work["server"].isin(servers)]
    return work


def deck_table(entries: pd.DataFrame, *, weighting: str = "dcg") -> pd.DataFrame:
    """One row per deck: its damage, its share of the player's total, whether it is the main deck."""
    decks = entries.groupby(DECK_KEYS, as_index=False).agg(
        rank=("rank", "first"), deck_score=("deck_score", "first"), size=("unit_id", "size")
    )
    total = decks.groupby(RANKER_KEYS)["deck_score"].transform("sum")
    decks["share"] = np.where(total > 0, decks["deck_score"] / total, 0.0)
    decks["is_main"] = decks["deck_score"] == decks.groupby(RANKER_KEYS)["deck_score"].transform("max")
    decks["w"] = rank_weight(decks["rank"], weighting)
    return decks


# --------------------------------------------------------------------------
# the season x unit table
# --------------------------------------------------------------------------

def season_summary(entries: pd.DataFrame, seasons: pd.DataFrame, *, weighting: str = "dcg") -> pd.DataFrame:
    """Per season: how many players and decks, when enikk last saw it, and whether it is over.

    ``collected_on`` is the (UTC) day enikk last collected the season and
    ``collected_until`` the end of that day. A season is ``final`` once that
    reaches its end; the season in progress is not, and its numbers are
    provisional.
    """
    if entries.empty:
        return pd.DataFrame()
    decks = deck_table(entries, weighting=weighting)
    main = decks[decks["is_main"]].drop_duplicates(RANKER_KEYS)
    collected = pd.to_datetime(entries.groupby("season")["collected_at"].max(), errors="coerce", utc=True)
    out = (
        decks.groupby("season")
        .agg(servers=("server", "nunique"), decks=("deck", "size"))
        .join(decks.drop_duplicates(RANKER_KEYS).groupby("season").size().rename("rankers"))
        .join(entries.groupby("season")["unit_id"].nunique().rename("units_fielded"))
        .join(((main["w"] * main["share"]).groupby(main["season"]).sum() / main.groupby("season")["w"].sum()).rename("main_deck_share"))
        .join(collected.rename("collected_on"))
        .join((collected + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)).rename("collected_until"))
        .reset_index()
    )
    out = out.merge(seasons, on="season", how="left")
    out["final"] = out["end_at"].notna() & (out["collected_until"] >= out["end_at"])
    return out


def unit_season(
    entries: pd.DataFrame,
    roster: pd.DataFrame,
    seasons: pd.DataFrame,
    *,
    weighting: str = "dcg",
    ridge: float = 20.0,
) -> pd.DataFrame:
    """One row per season and unit available in it, with every measurement.

    Columns:
      ``rankers``         players fielding the unit
      ``presence``        rank-weighted share of players fielding it
      ``deck_share``      average share of its player's damage that the unit's deck did
      ``main_deck_rate``  how often (rank-weighted) it sat in the player's top deck
      ``credit``          its share of the players' total damage (sums to 1 per season)
      ``lift``            credit x slots per player; 1.0 = an average meta slot
      ``deck_effect``     within-player deck regression: +0.12 = decks with it do 12% more
      ``best_rank``       best placement it appears in
      ``cp_median``       median combat power among the players fielding it
    """
    if entries.empty:
        return pd.DataFrame()
    decks = deck_table(entries, weighting=weighting)
    member = entries[DECK_KEYS + ["unit_id", "unit_cp"]].merge(
        decks[DECK_KEYS + ["rank", "share", "size", "is_main", "w"]], on=DECK_KEYS
    )
    member["credit_part"] = member["w"] * member["share"] / member["size"]
    rankers = decks.drop_duplicates(RANKER_KEYS)
    season_w = rankers.groupby("season")["w"].sum()
    slots = entries.groupby(RANKER_KEYS).size().groupby("season").median()

    users = member.drop_duplicates(RANKER_KEYS + ["unit_id"]).copy()
    users["w_share"] = users["w"] * users["share"]
    users["w_main"] = users["w"] * users["is_main"]
    keys = ["season", "unit_id"]
    per = users.groupby(keys).agg(
        rankers=("w", "size"),
        w_used=("w", "sum"),
        w_share=("w_share", "sum"),
        w_main=("w_main", "sum"),
        best_rank=("rank", "min"),
        cp_median=("unit_cp", "median"),
    )
    per["credit"] = member.groupby(keys)["credit_part"].sum()
    per = per.reset_index()
    per["presence"] = per["w_used"] / per["season"].map(season_w)
    per["deck_share"] = per["w_share"] / per["w_used"]
    per["main_deck_rate"] = per["w_main"] / per["w_used"]
    per["credit"] = per["credit"] / per["season"].map(season_w)
    per = per.drop(columns=["w_used", "w_share", "w_main"])

    effects = deck_effects(entries, decks, ridge=ridge)
    if not effects.empty:
        per = per.merge(effects, on=keys, how="left")
    else:
        per["deck_effect"] = np.nan

    # Every unit available that season gets a row, zero when nobody fielded it.
    released = release_instants(roster)
    starts = seasons.set_index("season")["start_at"]
    frames = [per]
    for season in season_order(per["season"]):
        start = starts.get(season)
        available = set(released.index[released.le(start).fillna(False)]) if start is not None and not pd.isna(start) else set()
        missing = sorted(available - set(per.loc[per["season"] == season, "unit_id"]))
        if missing:
            frames.append(pd.DataFrame({"season": season, "unit_id": missing, "rankers": 0, "presence": 0.0,
                                        "credit": 0.0, "deck_share": np.nan, "main_deck_rate": np.nan}))
    table = pd.concat(frames, ignore_index=True)
    table["rankers"] = table["rankers"].astype(int)
    table["slots"] = table["season"].map(slots).fillna(25.0)
    table["lift"] = table["credit"] * table["slots"]

    info = roster.drop_duplicates("unit_id").set_index("unit_id")
    table = table.join(info[[c for c in UNIT_INFO if c in info.columns]], on="unit_id")
    meta = seasons.set_index("season")[["boss_en", "boss_ko", "weak_element", "start_at", "end_at"]]
    table = table.join(meta, on="season")
    table["element_match"] = table["element"].fillna("") == table["weak_element"].fillna("?")
    return table.sort_values(["season", "lift", "unit_id"], ascending=[True, False, True]).reset_index(drop=True)


def deck_effects(entries: pd.DataFrame, decks: pd.DataFrame, *, ridge: float = 20.0) -> pd.DataFrame:
    """Within-player ridge regression of log deck damage on deck membership, per season.

    Demeaning inside each player removes the player's own level (account
    strength, skill), so a unit is judged against the player's other decks. The
    ridge penalty keeps units that always appear together from trading
    arbitrary credit between them - they split it evenly instead.
    """
    rows = []
    for season, group in entries.groupby("season"):
        season_decks = decks[(decks["season"] == season) & (decks["deck_score"] > 0)].reset_index(drop=True)
        if season_decks.empty:
            continue
        units = sorted(group["unit_id"].unique())
        column = {u: i for i, u in enumerate(units)}
        position = {key: i for i, key in enumerate(season_decks[["server", "player", "deck"]].itertuples(index=False, name=None))}
        design = np.zeros((len(season_decks), len(units)))
        for server, player, deck, unit in group[["server", "player", "deck", "unit_id"]].itertuples(index=False, name=None):
            row = position.get((server, player, deck))
            if row is not None:
                design[row, column[unit]] = 1.0
        player_code = pd.factorize(season_decks["server"] + "|" + season_decks["player"].astype(str))[0]
        x = pd.DataFrame(design)
        x = (x - x.groupby(player_code).transform("mean")).to_numpy()
        y = np.log(season_decks["deck_score"].to_numpy())
        y = y - pd.Series(y).groupby(player_code).transform("mean").to_numpy()
        w = season_decks["w"].to_numpy()
        lhs = x.T @ (w[:, None] * x) + ridge * np.eye(len(units))
        beta = np.linalg.solve(lhs, x.T @ (w * y))
        rows.append(pd.DataFrame({"season": season, "unit_id": units, "deck_effect": np.expm1(beta)}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


# --------------------------------------------------------------------------
# meta shift
# --------------------------------------------------------------------------

def jensen_shannon(p: np.ndarray, q: np.ndarray) -> float:
    """JSD in bits: 0 = identical metas, 1 = no overlap at all."""
    mask = (p > 0) | (q > 0)
    p, q = p[mask], q[mask]
    if p.sum() == 0 or q.sum() == 0:
        return float("nan")
    m = 0.5 * (p + q)

    def kl(a: np.ndarray, b: np.ndarray) -> float:
        nz = a > 0
        return float(np.sum(a[nz] * np.log2(a[nz] / b[nz])))

    return 0.5 * kl(p, m) + 0.5 * kl(q, m)


def meta_shift(table: pd.DataFrame, *, top_k: int = 10) -> pd.DataFrame:
    """How much the meta moved between consecutive seasons.

    The distribution compared is credit - each unit's share of the top players'
    damage - so ``total_variation`` reads directly as a percentage: 0.18 means
    18% of the damage moved to different units. ``newcomer_share`` is the part
    taken by units nobody fielded the season before, which separates "new units
    arrived" from "the order among existing units changed". ``effective_units``
    (the perplexity of the distribution) is how many units the meta behaves
    like it has.
    """
    seasons = season_order(table["season"])
    if len(seasons) < 2:
        return pd.DataFrame()
    pivot = table.pivot_table(index="unit_id", columns="season", values="credit", aggfunc="sum", fill_value=0.0)
    rows = []
    for previous, current in zip(seasons, seasons[1:]):
        p = pivot[previous].to_numpy()
        q = pivot[current].to_numpy()
        p = p / p.sum() if p.sum() > 0 else p
        q = q / q.sum() if q.sum() > 0 else q
        top_prev = set(pivot.index[np.argsort(-p, kind="stable")[:top_k]])
        top_curr = set(pivot.index[np.argsort(-q, kind="stable")[:top_k]])
        nz = q[q > 0]
        rows.append(
            {
                "season_from": previous,
                "season_to": current,
                "total_variation": float(0.5 * np.abs(p - q).sum()),
                "jsd": jensen_shannon(p, q),
                "top_k": top_k,
                "top_k_churn": len(top_curr - top_prev) / top_k,
                "entrants": ";".join(sorted(top_curr - top_prev)),
                "leavers": ";".join(sorted(top_prev - top_curr)),
                "newcomer_share": float(q[p == 0].sum()),
                "units_in_use": int((q > 0).sum()),
                "effective_units": float(math.exp(-np.sum(nz * np.log(nz)))) if nz.size else float("nan"),
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# synergy
# --------------------------------------------------------------------------

def synergy(entries: pd.DataFrame, *, min_decks: int = 20) -> pd.DataFrame:
    """Unit pairs that share a deck more often than chance, per season.

    Pointwise mutual information on co-occurrence within a deck. Decks are built
    around two- and three-unit cores, and PMI surfaces those cores without being
    dominated by whichever unit is simply everywhere.
    """
    if entries.empty:
        return pd.DataFrame()
    rows = []
    for season, group in entries.groupby("season"):
        deck_id = pd.factorize(group["server"] + "|" + group["player"].astype(str) + "|" + group["deck"].astype(str))[0]
        members = pd.DataFrame({"deck": deck_id, "unit_id": group["unit_id"].to_numpy()}).drop_duplicates()
        total = members["deck"].nunique()
        if total == 0:
            continue
        per_unit = members.groupby("unit_id")["deck"].nunique()
        pairs = members.merge(members, on="deck")
        pairs = pairs[pairs["unit_id_x"] < pairs["unit_id_y"]]
        counts = pairs.groupby(["unit_id_x", "unit_id_y"]).size().reset_index(name="together")
        counts = counts[counts["together"] >= min_decks]
        if counts.empty:
            continue
        p_x = counts["unit_id_x"].map(per_unit) / total
        p_y = counts["unit_id_y"].map(per_unit) / total
        counts["support"] = counts["together"] / total
        counts["pmi"] = np.log2(counts["support"] / (p_x * p_y))
        counts.insert(0, "season", season)
        rows.append(counts)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True).sort_values(["season", "pmi"], ascending=[True, False]).reset_index(drop=True)


# --------------------------------------------------------------------------
# per-unit arc
# --------------------------------------------------------------------------

def trajectories(table: pd.DataFrame) -> pd.DataFrame:
    """Each unit's arc: when it debuted, when it peaked, where it is now.

    ``retention`` (latest lift / peak lift) is where power creep shows: a unit
    whose retention has collapsed has been replaced, even if it still exists.
    """
    if table.empty:
        return pd.DataFrame()
    ordered = season_order(table["season"])
    position = {s: i for i, s in enumerate(ordered)}
    rows = []
    for unit_id, group in table.sort_values("season").groupby("unit_id"):
        used = group[group["lift"] > 0]
        if used.empty:
            continue
        peak = used.loc[used["lift"].idxmax()]
        latest = group.iloc[-1]
        rows.append(
            {
                "unit_id": unit_id,
                "name_ko": latest.get("name_ko", ""),
                "name_en": latest.get("name_en", ""),
                "debut_season": int(used.iloc[0]["season"]),
                "peak_season": int(peak["season"]),
                "peak_lift": float(peak["lift"]),
                "peak_tier": peak.get("tier", ""),
                "latest_season": int(latest["season"]),
                "latest_lift": float(latest["lift"]),
                "latest_tier": latest.get("tier", ""),
                "seasons_used": int(len(used)),
                "seasons_since_peak": position[int(latest["season"])] - position[int(peak["season"])],
                "retention": float(latest["lift"] / peak["lift"]) if peak["lift"] > 0 else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values(["peak_lift", "unit_id"], ascending=[False, True]).reset_index(drop=True)
