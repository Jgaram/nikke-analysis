"""체급 - what a unit is worth in a deck, measured by swaps, and the power creep it shows.

    python -m nikke_analysis.power     the numbers in docs/power.md (needs raid_entries.csv: `nikke build raids`)

The tiers are shares: a season's lift says how much of the top rankers' damage
a unit helped make *against the units of that season*. A unit that never
changes still loses lift as stronger units arrive, so the tiers cannot say how
much stronger the field got. This study gives every unit one number that does
not depend on the season - its 체급 - and reads the creep off it.

**체급 = what a deck does with the unit in it, against the same deck with 홍련.**
A deck's damage is taken to be the product of its five members' weights, so
``log(deck damage) = sum of the members' log weights``. Only a player's own
five decks are compared with each other (each deck against the player's
average), which takes the account's investment, the player's skill and the
boss out of the comparison. The members' combat power, against what the same
unit had in other rankers' hands that season, is one more term: how much
better built this copy is. One least-squares solve over every deck of every
season gives the weights; a unit is placed against units it never shared a
season with through the units both were swapped with.

The weight of a unit is the same in every season - a unit's kit does not change
- but kept apart where it plainly does: in seasons whose boss is weak to the
unit's element (``own``) and the rest (``other``), and before and after its
treasure (``T``). Each such combination is a *cell*.

What it is not: the unit's own damage. A deck does ``1 + share x (k - 1)``
times as much when one member does ``k`` times its own damage and made
``share`` of the deck's, so the deck multiple is a floor under the unit's own
multiple. Splitting the deck's damage into the members' own damage needs
damage per unit, which the rankings do not give - the same wall as the role
(CLAUDE.md), and the study does not try.

The tiers use one thing from here: ``split_weights``, the 체급 a deck's share is split by among its
members (season by season, from the decks up to that season). The study itself - the weights against
홍련, the creep, the field - feeds no table. The tier site draws it (메타 변화 · 파워 인플레) from ``site``,
computed once when the site is built: the page's parameters do not move it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .analyze import metrics, tiers
from .analyze.metrics import DECK_KEYS, RANKER_KEYS

REFERENCE = ("222", "own")  # 홍련 in seasons of her own element: launch roster, fielded in all 41 seasons
COMPARE = ("222", "225", "016", "511", "471", "520", "391", "191")  # 홍련 · 흑영 · 레드 후드 · 신데렐라 · 헤비암즈 · 브래디 · 아인 · 앨리스
RIDGE = 2.0  # pulls a cell seen in few decks toward its players' other decks
FREE = 1e-3  # the uncertainty is judged without that pull, so it shows what the decks alone pin down
MIN_DECKS = 30  # a cell from fewer decks is provisional
MAX_SE = 0.10  # ... and so is one whose log weight is less certain than this (about +-10%)
TOGETHER = 0.95  # two cells decked together this often, both ways, can only be weighed as a pair
SPLIT_TOP = 50  # the tiers' split is measured on these ranks of every server, whatever the tiers count
TOP = 25  # the field: the strongest this many cells available in a season
LAUNCH = pd.Timestamp("2022-11-04")
AGES = [0, 0.25, 0.5, 1, 1.5, 2, 2.5, 10]  # years since release, for the drift check


def cell_key(unit_id: pd.Series, treasure: pd.Series, own: pd.Series) -> pd.Series:
    return unit_id.astype(str) + np.where(treasure, "T", "") + np.where(own, ":own", ":other")


def cells(entries: pd.DataFrame, table: pd.DataFrame) -> pd.DataFrame:
    """Raid entries with the unit's cell that season: ``own`` (the boss was weak to it), ``treasure``
    (played with its treasure), ``cell``, and ``invest`` (log combat power over the median of the
    same unit that season - how much better built this copy is). ``table`` is the season x unit table."""
    info = pd.DataFrame({"season": table["season"].astype(int).to_numpy(),
                         "unit_id": table["unit_id"].astype(str).to_numpy(),
                         "own": tiers.flags(table, "element_match").to_numpy(),
                         "treasure": tiers.played_with_treasure(table).to_numpy()})
    out = entries.assign(unit_id=entries["unit_id"].astype(str)).merge(info, on=["season", "unit_id"], how="left")
    out["own"] = out["own"].eq(True)
    out["treasure"] = out["treasure"].eq(True)
    out["cell"] = cell_key(out["unit_id"], out["treasure"], out["own"])
    cp = np.log(pd.to_numeric(out["unit_cp"], errors="coerce").where(lambda v: v > 0))
    out["invest"] = (cp - cp.groupby([out["season"], out["unit_id"]]).transform("median")).fillna(0.0)
    return out


# --------------------------------------------------------------------------
# the solve
# --------------------------------------------------------------------------

@dataclass
class Fit:
    """The normal equations, kept per server so a server can be left out without redoing them."""
    cells: list[str]
    blocks: dict[str, tuple[np.ndarray, np.ndarray, float, float]]
    entries: pd.DataFrame  # the entries that went in, with ``row`` (their deck in ``decks``)
    decks: pd.DataFrame  # one row per deck: DECK_KEYS, ``w``, ``yd`` (log damage against the player's average)
    coef: np.ndarray | None = None  # log weight per cell, then the combat power term
    seasons: dict[int, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict)  # the sums, season by season

    @property
    def index(self) -> dict[str, int]:
        return {c: i for i, c in enumerate(self.cells)}

    def solve(self, servers=None, *, ridge: float = RIDGE, invest: bool = True) -> np.ndarray:
        A, b, _, _ = self.sums(servers)
        return _solve(A, b, len(self.cells), ridge=ridge, invest=invest)

    def through(self, season: int, *, ridge: float = RIDGE) -> np.ndarray:
        """The solve on the seasons up to ``season`` only - what the decks had shown by then."""
        chosen = [self.seasons[s] for s in self.seasons if s <= season]
        return _solve(sum(a for a, _ in chosen), sum(b for _, b in chosen), len(self.cells), ridge=ridge)

    def sums(self, servers=None):
        chosen = [s for s in self.blocks if servers is None or s in servers]
        A = sum(self.blocks[s][0] for s in chosen)
        b = sum(self.blocks[s][1] for s in chosen)
        return A, b, sum(self.blocks[s][2] for s in chosen), sum(self.blocks[s][3] for s in chosen)

    def uncertainty(self, reference: str) -> pd.Series:
        """The standard error of each cell's log weight against ``reference``, without the ridge's pull."""
        A, b, yy, ww = self.sums()
        inverse = np.linalg.inv(A + FREE * np.eye(len(b)))
        coef = inverse @ b
        sigma2 = (yy - 2 * coef @ b + coef @ A @ coef) / ww
        cov = inverse * sigma2
        r = self.index[reference]
        p = len(self.cells)
        var = np.diag(cov)[:p] + cov[r, r] - 2 * cov[:p, r]
        return pd.Series(np.sqrt(np.clip(var, 0, None)), index=self.cells)

    def predicted(self, coef: np.ndarray) -> np.ndarray:
        """Each deck's fitted log damage against its player's average."""
        part = coef[self.entries["col"].to_numpy()] + coef[-1] * self.entries["invest"].to_numpy()
        f = np.bincount(self.entries["row"].to_numpy(), weights=part, minlength=len(self.decks))
        return f - pd.Series(f).groupby(self.decks["ranker"].to_numpy()).transform("mean").to_numpy()


def _solve(A: np.ndarray, b: np.ndarray, p: int, *, ridge: float, invest: bool = True) -> np.ndarray:
    if not invest:
        A, b = A[:p, :p], b[:p]
    penalty = ridge * np.eye(len(b))
    if invest:
        penalty[p, p] = 1e-9  # the combat power term is not pulled - only kept solvable when it never varies
    coef = np.linalg.solve(A + penalty, b)
    return coef if invest else np.append(coef, 0.0)


def fit(entries: pd.DataFrame, *, weighting: str = "dcg") -> Fit:
    """The normal equations of every deck that did damage (``entries`` from ``cells``)."""
    entries = entries[pd.to_numeric(entries["deck_score"], errors="coerce") > 0]
    decks = metrics.deck_table(entries, weighting=weighting).reset_index(drop=True)
    decks["row"] = np.arange(len(decks))
    decks["ranker"] = pd.factorize(pd.MultiIndex.from_frame(decks[RANKER_KEYS]))[0]
    y = np.log(decks["deck_score"].to_numpy(dtype=float))
    decks["yd"] = y - pd.Series(y).groupby(decks["ranker"]).transform("mean").to_numpy()
    names = sorted(entries["cell"].unique())
    col = {c: i for i, c in enumerate(names)}
    e = entries.merge(decks[DECK_KEYS + ["row"]], on=DECK_KEYS)
    e["col"] = e["cell"].map(col)
    p = len(names) + 1
    blocks: dict[str, tuple] = {}
    by_season: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    members = dict(tuple(e.groupby(["season", "server"])))
    for (season, server), d in decks.groupby(["season", "server"]):
        m = members[(season, server)]
        local = pd.Series(np.arange(len(d)), index=d["row"].to_numpy())
        r = local[m["row"].to_numpy()].to_numpy()
        X = np.zeros((len(d), p))
        X[r, m["col"].to_numpy()] = 1.0
        np.add.at(X[:, -1], r, m["invest"].to_numpy())
        X -= pd.DataFrame(X).groupby(d["ranker"].to_numpy()).transform("mean").to_numpy()
        yd, w = d["yd"].to_numpy(), d["w"].to_numpy()
        dA, db = X.T @ (w[:, None] * X), X.T @ (w * yd)
        A, b, yy, ww = blocks.get(server, (np.zeros((p, p)), np.zeros(p), 0.0, 0.0))
        blocks[server] = (A + dA, b + db, yy + float(w @ (yd * yd)), ww + float(w.sum()))
        sA, sb = by_season.get(int(season), (np.zeros((p, p)), np.zeros(p)))
        by_season[int(season)] = (sA + dA, sb + db)
    out = Fit(cells=names, blocks=blocks, entries=e, decks=decks, seasons=by_season)
    out.coef = out.solve()
    return out


# --------------------------------------------------------------------------
# the weights, and the cells that cannot be weighed
# --------------------------------------------------------------------------

def teammates(entries: pd.DataFrame) -> pd.DataFrame:
    """Per cell, the cell it was most often decked with and how often (share of its decks)."""
    pairs = entries[DECK_KEYS + ["cell"]].merge(entries[DECK_KEYS + ["cell"]], on=DECK_KEYS, suffixes=("", "_mate"))
    pairs = pairs[pairs["cell"] != pairs["cell_mate"]]
    counts = pairs.groupby(["cell", "cell_mate"]).size().rename("n").reset_index()
    best = counts.sort_values(["n", "cell_mate"], ascending=[False, True]).drop_duplicates("cell").set_index("cell")
    decks = entries.groupby("cell").size()
    return pd.DataFrame({"partner": best["cell_mate"], "together": best["n"] / decks.reindex(best.index)})


def weights(result: Fit, *, reference: tuple[str, str] = REFERENCE, coef: np.ndarray | None = None) -> pd.DataFrame:
    """One row per cell: ``weight`` (deck multiple against ``reference``), ``log``, ``se``, ``decks``,
    ``partner``/``together`` and ``status``: ``ok``, ``provisional`` (few decks or uncertain) or
    ``pair`` (always decked with one other cell - only the two together can be weighed)."""
    ref = f"{reference[0]}:{reference[1]}"
    coef = result.coef if coef is None else coef
    beta = pd.Series(coef[:-1], index=result.cells)
    out = pd.DataFrame({"cell": result.cells, "log": (beta - beta[ref]).to_numpy()})
    out["weight"] = np.exp(out["log"])
    out["se"] = result.uncertainty(ref).to_numpy()
    out["decks"] = out["cell"].map(result.entries.groupby("cell").size())
    first = result.entries.drop_duplicates("cell").set_index("cell")
    for column in ("unit_id", "own", "treasure"):
        out[column] = out["cell"].map(first[column])
    out = out.join(teammates(result.entries), on="cell")
    mate = out.set_index("cell")
    mutual = out["partner"].map(mate["partner"]).eq(out["cell"]) & out["partner"].map(mate["together"]).ge(TOGETHER)
    paired = (out["together"] >= TOGETHER) & mutual & (out["se"] > MAX_SE)
    out["status"] = np.where(paired, "pair", np.where((out["decks"] < MIN_DECKS) | (out["se"] > MAX_SE), "provisional", "ok"))
    out["pair_weight"] = np.where(paired, np.exp(out["log"] + out["partner"].map(mate["log"])), np.nan)
    return out


def unobserved(entries: pd.DataFrame, table: pd.DataFrame) -> list[str]:
    """Units in the season table that no deck ever fielded: no weight, which is not a weight of 0."""
    return sorted(set(table["unit_id"].astype(str)) - set(entries["unit_id"].astype(str)))


# --------------------------------------------------------------------------
# the tiers' split of a deck's share
# --------------------------------------------------------------------------

def split_weights(entries: pd.DataFrame, roster: pd.DataFrame, seasons: pd.DataFrame) -> pd.DataFrame:
    """Per season and unit fielded in it, the log 체급 its deck's share is split by (metrics.unit_season):
    the unit's cell that season, solved on the decks of the seasons up to it - what the decks had shown
    by then, so a past tier never leans on a later season. Measured once on every ranked deck (every
    server, ranks 1-``SPLIT_TOP``, rank weighted): the tiers' parameters choose whose decks count, not
    how a deck is split. Empty without decks."""
    entries = metrics.select_population(entries, top_n=SPLIT_TOP)
    if entries.empty:
        return pd.DataFrame(columns=["season", "unit_id", "weight"])
    entries = entries.assign(unit_id=entries["unit_id"].astype(str))
    pairs = entries[["season", "unit_id"]].drop_duplicates().reset_index(drop=True)
    result = fit(cells(entries, metrics.season_rows(pairs, roster, seasons)))
    index = result.index
    used = result.entries.drop_duplicates(["season", "unit_id"])
    frames = []
    for season, rows in used.groupby("season"):
        coef = result.through(int(season))
        frames.append(pd.DataFrame({"season": int(season), "unit_id": rows["unit_id"].to_numpy(),
                                    "weight": coef[rows["cell"].map(index).to_numpy()]}))
    return pd.concat(frames, ignore_index=True).sort_values(["season", "unit_id"]).reset_index(drop=True)


# --------------------------------------------------------------------------
# the creep
# --------------------------------------------------------------------------

def _by_unit(frame: pd.DataFrame, column: str) -> pd.Series:
    first = frame.drop_duplicates("unit_id")
    return pd.Series(first[column].to_numpy(), index=first["unit_id"].astype(str).to_numpy())


def released(units: pd.Series, roster: pd.DataFrame) -> pd.Series:
    return units.astype(str).map(pd.to_datetime(_by_unit(roster, "release_date"), errors="coerce"))


def years_out(units: pd.Series, roster: pd.DataFrame) -> pd.Series:
    return (released(units, roster) - LAUNCH).dt.days / 365.25


def own_share(history: pd.DataFrame) -> pd.DataFrame:
    """Per unit, before and after its treasure: the share of all the seasons whose boss was weak to
    one of its elements (its own, the ones its skill adds and - after the treasure - the treasure's).
    Without the seasons' weakness, the share of the unit's own seasons that matched."""
    first = history.drop_duplicates("unit_id")
    first = first.set_index(first["unit_id"].astype(str))
    if "weak_element" not in history.columns or "element" not in history.columns:
        share = tiers.flags(history, "element_match").groupby(history["unit_id"].astype(str)).mean()
        return pd.DataFrame([{"unit_id": u, "treasure": t, "share": float(v)} for u, v in share.items() for t in (False, True)])
    weak = history.drop_duplicates("season")["weak_element"].dropna().value_counts(normalize=True)
    rows = []
    for unit, info in first.iterrows():
        mine = {info.get("element")} | set(metrics.listed_elements(info.get("extra_elements")))
        for treasure in (False, True):
            elements = mine | (set(metrics.listed_elements(info.get("treasure_elements"))) if treasure else set())
            rows.append({"unit_id": unit, "treasure": treasure, "share": float(weak.reindex(sorted(e for e in elements if e)).fillna(0).sum())})
    return pd.DataFrame(rows)


def overall(table: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    """The 종합 체급 of every unit before and after its treasure: its own-season and other-season
    weights mixed (in logs) by how often the boss really was weak to it (``own_share``) - what it
    adds over the seasons as they come. Only with both sides weighed and neither a pair; well weighed
    (``ok``) when both are, else provisional. ``se`` takes the two sides as independent."""
    cells = table[table["status"] != "pair"].dropna(subset=["log"])
    cells = cells.assign(treasure=cells["treasure"].astype(bool), unit_id=cells["unit_id"].astype(str))
    keys, columns = ["unit_id", "treasure"], ["unit_id", "treasure", "log", "se", "status"]
    own = cells.loc[cells["own"].astype(bool), columns]
    other = cells.loc[~cells["own"].astype(bool), columns]
    out = own.merge(other, on=keys, suffixes=("_own", "_other")).merge(own_share(history), on=keys, how="left")
    p = out["share"].fillna(0.0)
    return pd.DataFrame({
        "unit_id": out["unit_id"], "treasure": out["treasure"], "share": p,
        "log": p * out["log_own"] + (1 - p) * out["log_other"],
        "se": np.sqrt((p * out["se_own"]) ** 2 + ((1 - p) * out["se_other"]) ** 2),
        "status": np.where((out["status_own"] == "ok") & (out["status_other"] == "ok"), "ok", "provisional"),
    })


def creep(table: pd.DataFrame, roster: pd.DataFrame, combined: pd.DataFrame | None = None) -> pd.Series:
    """How much stronger, per year of release date, units came out: the deck multiple a year later
    buys, by side (``own`` / ``other``, and ``overall`` given the 종합 체급). Cells weighed well
    (``ok``) and without a treasure."""
    out = {}
    for side, rows in _sides(table, combined):
        years = years_out(rows["unit_id"], roster)
        out[side] = float(np.exp(np.polyfit(years, rows["log"], 1)[0]))
    return pd.Series(out)


def by_year(table: pd.DataFrame, roster: pd.DataFrame, combined: pd.DataFrame | None = None) -> pd.DataFrame:
    """Average weight (geometric) of the cells weighed well, by release year and side."""
    frames = []
    for side, rows in _sides(table, combined):
        frames.append(rows.assign(side=side, year=released(rows["unit_id"], roster).dt.year.to_numpy()))
    rows = pd.concat(frames, ignore_index=True)
    return rows.groupby(["side", "year"])["log"].agg(["mean", "size"]).assign(weight=lambda f: np.exp(f["mean"]))


def _sides(table: pd.DataFrame, combined: pd.DataFrame | None):
    """The well weighed rows without a treasure, per side: the 종합 first when given."""
    pick = lambda f: f[(f["status"] == "ok") & ~f["treasure"].astype(bool)]
    if combined is not None:
        yield "overall", pick(combined)
    rows = pick(table)
    for side, own in (("own", True), ("other", False)):
        yield side, rows[rows["own"].astype(bool) == own]


def field_strength(table: pd.DataFrame, history: pd.DataFrame) -> pd.Series:
    """Per season, the average weight (geometric) of the ``TOP`` strongest cells available then -
    every unit out at its start, in the cell it would have played that season, weighed or not."""
    rows = pd.DataFrame({"season": history["season"].astype(int).to_numpy(),
                         "cell": cell_key(history["unit_id"].astype(str), tiers.played_with_treasure(history),
                                          tiers.flags(history, "element_match")).to_numpy()})
    rows["log"] = rows["cell"].map(table.set_index("cell")["log"])
    top = rows.dropna(subset=["log"]).sort_values("log", ascending=False).groupby("season").head(TOP)
    return np.exp(top.groupby("season")["log"].mean())


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------

def drift(result: Fit, history: pd.DataFrame, roster: pd.DataFrame) -> pd.DataFrame:
    """Does a unit's weight hold over its life? The decks' misses (actual - fitted, log) by the age of
    each member when the season started. A unit that wore out would be over-fitted when old."""
    miss = result.decks["yd"].to_numpy() - result.predicted(result.coef)
    e = result.entries
    first = history.drop_duplicates("season")
    starts = pd.Series(pd.to_datetime(first["start_at"], errors="coerce", utc=True).dt.tz_localize(None).to_numpy(),
                       index=first["season"].astype(int).to_numpy())
    age = (e["season"].map(starts) - released(e["unit_id"], roster)).dt.days / 365.25
    band = pd.cut(age, AGES, right=False)
    return pd.DataFrame({"miss": miss[e["row"].to_numpy()], "band": band}).groupby("band", observed=True)["miss"].agg(["mean", "size"])


def swap_check(result: Fit, *, ridge: float = RIDGE) -> dict[str, float]:
    """The swaps rankers made themselves: decks of the same season and server that share four members.
    With one server left out at a time, the weights from the other servers say how much more the one
    deck does than the other; ``slope`` is how much of that the decks really did (1 = all of it),
    from the differences inside each group of such decks."""
    e = result.entries
    full = e.groupby("row")["cell"].agg(lambda c: sorted(c))
    full = full[full.map(len) == 5]
    season = result.decks["season"].to_numpy()
    server_of = result.decks["server"].to_numpy()
    yd = result.decks["yd"].to_numpy()
    frames = []
    for server in result.blocks:
        pred = result.predicted(result.solve([s for s in result.blocks if s != server], ridge=ridge))
        mine = full[server_of[full.index] == server]
        keys, rows = [], []
        for row, members in mine.items():
            for drop in range(5):
                keys.append(f"{season[row]}|{server}|" + ",".join(members[:drop] + members[drop + 1:]))
                rows.append(row)
        rows = np.array(rows, dtype=int)
        frames.append(pd.DataFrame({"key": keys, "pred": pred[rows], "obs": yd[rows]}))
    groups = pd.concat(frames, ignore_index=True)
    groups = groups[groups.groupby("key")["key"].transform("size") >= 2]
    x = groups["pred"] - groups.groupby("key")["pred"].transform("mean")
    y = groups["obs"] - groups.groupby("key")["obs"].transform("mean")
    return {"slope": float((x * y).sum() / (x * x).sum()), "corr": float(np.corrcoef(x, y)[0, 1]),
            "decks": float(groups["key"].nunique())}


# --------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------

def load(data_dir=None, config=None):
    """raid_entries (Solo Raid, the configured servers), the committed season x unit table and the roster."""
    from .analyze.pipeline import load_inputs
    from .paths import processed_dir
    from .tierlist import TierBook

    directory = data_dir or processed_dir()
    if not (directory / "raid_entries.csv").is_file():
        raise RuntimeError("체급은 덱 대미지로 잰다: raid_entries.csv 가 필요하다 - `nikke build raids` (오프라인, 몇 초)")
    inputs = load_inputs(directory)
    book = TierBook.load(directory)
    entries = inputs["entries"]
    if "content" in entries.columns:
        entries = entries[entries["content"] == "soloraid"]
    config = config or book.config
    entries = metrics.select_population(entries, top_n=config.top_n, servers=config.servers,
                                        exclude=config.exclude_servers)
    return entries, book.history, inputs["roster"], config


def payload(entries: pd.DataFrame, history: pd.DataFrame, *, weighting: str = "dcg",
            reference: tuple[str, str] = REFERENCE) -> dict | None:
    """What the site's 메타 변화 · 파워 인플레 view draws: every cell (``log`` weight against ``reference``,
    ``se``, ``decks``, ``status``, the partner of a pair and the pair's ``pairLog``), the 종합 체급 of every
    unit before and after its treasure (``overall``: ``log``, ``se``, ``share``, ``status``), the field season
    by season (``TOP`` strongest cells out then, geometric mean) and the season each unit's treasure
    first played. None when the reference never played (no scale to put the weights on)."""
    result = fit(cells(entries, history), weighting=weighting)
    if f"{reference[0]}:{reference[1]}" not in result.cells:
        return None
    table = weights(result, reference=reference)
    combined = overall(table, history)
    field = field_strength(table, history)
    played = history[tiers.played_with_treasure(history).to_numpy()]
    treasure_from = played.groupby(played["unit_id"].astype(str))["season"].min()
    rounded = lambda v: round(float(v), 4) if np.isfinite(v) else None
    return {
        "reference": reference[0],
        "decks": int(len(result.decks)),
        "top": TOP,
        "minDecks": MIN_DECKS,
        "maxSe": MAX_SE,
        "cells": [{"unit": str(r.unit_id), "own": bool(r.own), "treasure": bool(r.treasure), "log": rounded(r.log),
                   "se": rounded(r.se), "decks": int(r.decks), "status": str(r.status),
                   "partner": str(r.partner).split(":")[0].rstrip("T") if r.status == "pair" else None,
                   "pairLog": rounded(np.log(r.pair_weight)) if r.status == "pair" else None}
                  for r in table.sort_values("cell").itertuples()],
        "overall": [{"unit": str(r.unit_id), "treasure": bool(r.treasure), "log": rounded(r.log), "se": rounded(r.se),
                     "share": rounded(r.share), "status": str(r.status)}
                    for r in combined.sort_values(["unit_id", "treasure"]).itertuples()],
        "field": [[int(season), rounded(value)] for season, value in field.items()],
        "treasureFrom": {unit: int(season) for unit, season in sorted(treasure_from.items())},
    }


def site(data_dir=None, config=None) -> dict | None:
    """``payload`` from the processed tables (the site's ``data/power.json``), None without the metric tables."""
    from .paths import processed_dir

    directory = data_dir or processed_dir()
    if not (directory / "metrics_unit_season.csv").is_file():
        return None
    entries, history, _roster, config = load(directory, config)
    history = history.assign(season=pd.to_numeric(history["season"]).astype(int))
    return payload(entries, history, weighting=config.rank_weighting)


def report(data_dir=None) -> str:
    raw, history, roster, config = load(data_dir)
    entries = cells(raw, history)
    result = fit(entries, weighting=config.rank_weighting)
    table = weights(result)
    ko, en = _by_unit(history, "name_ko"), _by_unit(history, "name_en")
    label = ko.where(ko.fillna("") != "", en)
    name = lambda cell: label.get(cell.split(":")[0].rstrip("T"), cell) + (" (애장품)" if "T:" in cell else "")
    by_cell = table.set_index("cell")
    servers = sorted(result.blocks)
    left_out = {s: weights(result, coef=result.solve([x for x in servers if x != s])).set_index("cell") for s in servers}
    newest = int(entries["season"].max())
    lines = [f"시즌 1-{newest} · 덱 {len(result.decks):,}개 · 칸 {len(result.cells)}개 (니케 × 자기/다른 속성 시즌 × 애장품 전/후) · "
             f"체급 = 덱 대미지 배수, 홍련이 자기 속성 시즌에 쓰일 때 = 1", ""]

    combined = overall(table, history)
    by_unit = combined[~combined["treasure"]].set_index("unit_id")
    left_combined = {s: overall(left_out[s].reset_index(), history) for s in servers}
    lines.append("1. 비교 (± = 표준오차, [ ] = 서버 하나씩 뺀 여섯 번의 최소-최대)")
    for unit in COMPARE:
        if unit in by_unit.index:
            r = by_unit.loc[unit]
            spread = [np.exp(f.set_index("unit_id").loc[unit, "log"]) for f in (c[~c["treasure"]] for c in left_combined.values())
                      if unit in set(f["unit_id"])]
            lines.append(f"   {name(unit + ':own'):<16} 종합 {np.exp(r.log):.2f} ±{r.se * np.exp(r.log):.2f} "
                         f"[{min(spread):.2f}-{max(spread):.2f}] · 자기 속성 시즌 {r.share:.0%} · {STATUS_KO[r.status]}")
        for side in ("own", "other"):
            cell = f"{unit}:{side}"
            if cell not in by_cell.index:
                continue
            r = by_cell.loc[cell]
            spread = [np.exp(left_out[s].at[cell, "log"]) for s in servers]
            lines.append(f"   {name(cell):<16} {'자기' if side == 'own' else '다른'} {r.weight:.2f} ±{r.se * r.weight:.2f} "
                         f"[{min(spread):.2f}-{max(spread):.2f}] · 덱 {int(r.decks)} · {STATUS_KO[r.status]}")
    lines.append("")

    lines.append("2. 체급 상위 (잘 잰 칸)")
    good = table[table["status"] == "ok"]
    top = combined[(combined["status"] == "ok") & ~combined["treasure"]].nlargest(15, "log")
    lines.append("   종합: " + " · ".join(f"{name(u + ':own')} {np.exp(v):.2f}" for u, v in zip(top["unit_id"], top["log"])))
    for own, size in ((True, 15), (False, 10)):
        top = good[good["own"] == own].nlargest(size, "log")
        lines.append(f"   {'자기' if own else '다른'} 속성 시즌: " + " · ".join(f"{name(c)} {w:.2f}" for c, w in zip(top["cell"], top["weight"])))
    lines.append("")

    lines.append("3. 인플레: 출시일이 1년 늦을 때 체급 (잘 잰 칸, 애장품 전)")
    rates = creep(table, roster, combined)
    spread = pd.DataFrame({s: creep(left_out[s].reset_index(), roster, left_combined[s]) for s in servers})
    for side in ("overall", "own", "other"):
        lines.append(f"   {SIDE_KO[side]}: x{rates[side]:.3f} "
                     f"[서버 하나씩 빼면 x{spread.loc[side].min():.3f}-x{spread.loc[side].max():.3f}]")
    years = by_year(table, roster, combined)
    for side in ("overall", "own", "other"):
        part = years.loc[side]
        lines.append(f"   출시 연도별 평균 ({SIDE_KO[side]}): " + " · ".join(
            f"{y} {r.weight:.2f} ({int(r['size'])})" for y, r in part.iterrows()))
    field = field_strength(table, history)
    lines.append(f"   시즌마다 쓸 수 있던 상위 {TOP}칸의 평균 체급: " + " · ".join(
        f"S{s} {v:.2f}" for s, v in field.items() if s % 5 == 1 or s == field.index.max()))
    lines.append("")

    lines.append("4. 체급은 생애 내내 같은가: 덱 대미지의 빗나감(실제 - 예측, 로그) 평균, 멤버의 출시 뒤 경과별")
    lines.append("   " + " · ".join(f"{b.left:g}-{b.right:g}년 {r['mean']:+.3f}" for b, r in drift(result, history, roster).iterrows()))
    lines.append("")

    lines.append("5. 랭커들의 교체 실험: 같은 시즌·서버에서 넷이 같고 하나가 다른 덱들 (서버 하나씩 빼고 잰 체급으로)")
    check = swap_check(result)
    lines.append(f"   묶음 {check['decks']:,.0f}개 · 실제 차이 / 예측 차이 = {check['slope']:.2f} · 상관 {check['corr']:.2f}")
    lines.append("")

    lines.append("6. 육성 보정 (전투력이 같은 니케 중앙값보다 높은 만큼)")
    bare = weights(result, coef=result.solve(invest=False)).set_index("cell")["log"]
    moved = (by_cell["log"] - bare).abs()[by_cell["status"] == "ok"]
    lines.append(f"   멤버 하나의 전투력 10% → 덱 대미지 {np.expm1(result.coef[-1] * np.log(1.1)):+.1%} · "
                 f"보정이 바꾼 체급: 평균 {np.expm1(moved.mean()):.1%}, 최대 {np.expm1(moved.max()):.1%}")
    lines.append("")

    lines.append("7. 잴 수 없는 니케")
    never = unobserved(raw, history)
    lines.append(f"   덱에 한 번도 안 들어감 {len(never)}명: " + ", ".join(label.get(u, u) for u in never))
    measured = set(table.loc[table["status"] == "ok", "unit_id"])
    thin = sorted(set(table["unit_id"]) - measured)
    lines.append(f"   잘 잰 칸이 하나도 없음(덱 {MIN_DECKS}개 미만이거나 ±{MAX_SE:.0%} 넘게 불확실) {len(thin)}명: "
                 + ", ".join(label.get(u, u) for u in thin))
    pairs = table[table["status"] == "pair"]
    shown = set()
    for r in pairs.itertuples():
        if r.partner in shown:
            continue
        shown.add(r.cell)
        lines.append(f"   짝으로만: {name(r.cell)} + {name(r.partner)} ({r.together:.0%} 같이, 덱 {int(r.decks)}) "
                     f"→ 둘이 홍련 둘 자리에 {r.pair_weight:.2f}배")
    lines.append(f"   잘 잰 니케 {len(measured)}명 / 덱에 들어간 니케 {table['unit_id'].nunique()}명")
    return "\n".join(lines)


STATUS_KO = {"ok": "잘 잼", "provisional": "잠정", "pair": "짝으로만"}
SIDE_KO = {"overall": "종합", "own": "자기 속성 시즌", "other": "다른 속성 시즌"}


if __name__ == "__main__":
    print(report())
