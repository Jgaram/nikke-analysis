"""Render the metric tables as charts.

Seven charts, each answering one question:

``tier-snapshot``      what was each unit's tier in the latest finished season?
``tier-trajectories``  how did these units' tiers move, season by season?
``tier-heatmap``       every strong unit's tier in every season, at a glance
``element-tiers``      what is each unit worth against each boss weakness, now?
``tier-distribution``  how many units reach each tier, season by season?
``meta-shift``         how much did the meta move, season to season?
``patch-impact``       which patch windows moved the meta most?

Every chart is rendered in both light and dark. The dark version uses its own
validated steps rather than an inverted copy of the light one.

Units are drawn as their faces, elements and classes as their icons
(``data/assets/icons/``, fetched by ``nikke collect icons``), so no chart spells
out a unit's name or an element. A unit whose face is not on disk yet falls
back to its name - in Korean when a Hangul font is installed, in English
otherwise - and so does an element or class without its icon.

Charts of another server sample (``nikke viz --exclude NA``) say so at the end
of every subtitle, so a copied image does not pass for the whole population.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # no display in CI or a cloud session
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, PathPatch, Rectangle
from matplotlib.path import Path as MplPath

from ..analyze.metrics import ELEMENTS, season_order
from ..analyze.tiers import load_tier_config
from ..paths import processed_dir, reports_dir
from . import theme as th
from .icons import Icons, line, place

log = logging.getLogger(__name__)

SEASON_COLUMNS = ("season", "season_from", "season_to")
ELEMENT_SHORT = {"Fire": "Fire", "Water": "Water", "Wind": "Wind", "Iron": "Iron", "Electric": "Elec."}
ELEMENT_INITIAL = {"Fire": "F", "Water": "Wa", "Wind": "Wi", "Iron": "I", "Electric": "E"}

# The server sample when it is not the configured one ("all servers but NA");
# render_all sets it for the length of a run and every subtitle ends with it.
_sample_caption = ""


def _read(name: str, directory: Path) -> pd.DataFrame:
    """Read a metric table with ids kept as text and seasons as integers."""
    path = directory / name
    if not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame()
    frame = pd.read_csv(path, dtype={"unit_id": str})
    for column in SEASON_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
    return frame


class Names:
    """Korean display names when the font can draw them, English otherwise."""

    def __init__(self) -> None:
        self.korean = th.hangul_font() is not None

    def __call__(self, row: Any) -> str:
        ko, en = row.get("name_ko"), row.get("name_en")
        if self.korean and isinstance(ko, str) and ko:
            return ko
        if isinstance(en, str) and en:
            return en
        return str(row.get("unit_id", ""))


def _frame(fig, ax, theme: th.Theme, *, title: str, subtitle: str | list = "", legend_cols: int = 0) -> None:
    """Title, subtitle and legend in one place, positioned in points.

    Axes-fraction positioning collides as soon as a chart is resized, so both
    lines are offset from the axes in typographic points and the legend sits
    below the plot where it can never overlap a mark. A subtitle given as a
    list mixes words and icons (see ``icons.line``).
    """
    ax.set_title("")
    ax.annotate(title, (0, 1), xycoords="axes fraction", textcoords="offset points", xytext=(0, 34),
                fontsize=14, fontweight="bold", color=theme.ink_primary, va="bottom", annotation_clip=False)
    if isinstance(subtitle, list):
        parts = subtitle + ([f"· {_sample_caption}"] if _sample_caption else [])
        place(ax, line(parts, height_pt=11, fontsize=9, color=theme.ink_muted), (0, 1),
              xycoords="axes fraction", offset=(0, 16), align=(0, 0))
    else:
        if _sample_caption:
            subtitle = f"{subtitle} · {_sample_caption}" if subtitle else _sample_caption
        if subtitle:
            ax.annotate(subtitle, (0, 1), xycoords="axes fraction", textcoords="offset points", xytext=(0, 16),
                        fontsize=9, color=theme.ink_muted, va="bottom", annotation_clip=False)
    if legend_cols:
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncols=legend_cols, frameon=False)


def _tier_color(tier: str, theme: th.Theme, order: list[str]) -> str:
    return th.tier_color(tier, theme, order)


def _rounded_hbar(ax, y: float, width: float, height: float, color: str, radius_px: float = 4.0) -> None:
    """A horizontal bar, square at the baseline, with a 4px rounded data-end."""
    if width <= 0:
        return
    dx, dy = th.px_to_data(ax, radius_px)
    rx, ry = min(dx, width / 2), min(dy, height / 2)
    top, bottom = y + height / 2, y - height / 2
    points = [(0.0, bottom), (width - rx, bottom)]
    points += [(width - rx + rx * np.cos(a), bottom + ry + ry * np.sin(a)) for a in np.linspace(-np.pi / 2, 0, 8)]
    points.append((width, top - ry))
    points += [(width - rx + rx * np.cos(a), top - ry + ry * np.sin(a)) for a in np.linspace(0, np.pi / 2, 8)]
    points += [(0.0, top), (0.0, bottom)]
    codes = [MplPath.MOVETO] + [MplPath.LINETO] * (len(points) - 2) + [MplPath.CLOSEPOLY]
    ax.add_patch(PathPatch(MplPath(points, codes), facecolor=color, linewidth=0, zorder=2))


def _tier_legend(order: list[str], theme: th.Theme, *, extra: list | None = None) -> list:
    handles = [Patch(facecolor=_tier_color(t, theme, order), label=t) for t in order]
    return handles + (extra or [])


def _element_part(icons: Icons, element: Any, height_pt: float, *, word: str = "{}") -> Any:
    """An element's icon at ``height_pt``, or the element's name when there is none."""
    image = icons.element(element)
    if image is not None:
        return (image, height_pt)
    return word.format(element) if isinstance(element, str) and element else ""


def _unit_parts(icons: Icons, names: Names, row: Any, face_pt: float) -> list:
    """A unit as its face with its element beside it, or its name and element initial."""
    face = icons.face(str(row.get("unit_id", "")))
    element = row.get("element")
    if face is not None:
        return [(face, face_pt), _element_part(icons, element, face_pt * 0.62)]
    tag = _element_part(icons, element, face_pt * 0.62, word="")
    if not tag and isinstance(element, str) and element:
        tag = f"({ELEMENT_INITIAL.get(element, '?')})"
    return [names(row), tag]


def _label_rows(ax, theme: th.Theme, rows: list[list], *, face_pt: float, fontsize: float = 8.5) -> None:
    """One label per row of a y-axis, right-aligned against the plot like tick labels."""
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([])
    for y, parts in enumerate(rows):
        place(ax, line(parts, height_pt=face_pt, fontsize=fontsize, color=theme.ink_secondary, sep_pt=2.5),
              (0, y), xycoords=("axes fraction", "data"), offset=(-6, 0), align=(1, 0.5))


# --------------------------------------------------------------------------
# tiers
# --------------------------------------------------------------------------

def chart_tier_snapshot(history: pd.DataFrame, seasons: pd.DataFrame, theme: th.Theme, out: Path,
                        names: Names, icons: Icons) -> Path | None:
    """Every unit that mattered in the latest finished season, by lift and tier.

    The tick on each bar is the unit's overall tier score once that season was
    over - where a bar and its tick disagree, the season suited the unit (or
    did not) more than usual.
    """
    if history.empty or seasons.empty:
        return None
    final = seasons[seasons["final"].astype(str).str.lower().isin(("true", "1"))]
    if final.empty:
        return None
    season = int(final["season"].max())
    meta = final[final["season"] == season].iloc[0]
    order = load_tier_config().tier_order
    table = history[(history["season"] == season) & (history["lift"] >= load_tier_config().cut("C"))]
    table = table.sort_values(["lift", "unit_id"], ascending=[True, True])
    if table.empty:
        return None
    n = len(table)
    fig, ax = plt.subplots(figsize=(9.2, 0.34 * n + 1.8))
    ax.set_xlim(0, max(2.0, float(table["lift"].max()) * 1.12))
    ax.set_ylim(-0.7, n - 0.3)
    fig.canvas.draw()
    for i, (_, row) in enumerate(table.iterrows()):
        _rounded_hbar(ax, i, float(row["lift"]), 0.62, _tier_color(row["tier"], theme, order))
    ax.scatter(table["overall"], range(n), marker="|", s=170, linewidths=2.2, color=theme.ink_primary, zorder=4)
    _label_rows(ax, theme, [_unit_parts(icons, names, r, 21) for _, r in table.iterrows()], face_pt=21, fontsize=9)
    ax.tick_params(axis="y", length=0)
    for label, cut in load_tier_config().cuts[:-1]:
        ax.axvline(cut, color=theme.grid, linewidth=1, zorder=1)
        ax.annotate(label, (cut, n - 0.3), textcoords="offset points", xytext=(4, 2), fontsize=9,
                    color=theme.ink_muted, va="bottom", annotation_clip=False)
    ax.grid(False)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.set_xlabel("Lift (1.0 = an average member of a player's 25 units)")
    handles = _tier_legend(order[:-1], theme, extra=[
        Line2D([], [], marker="|", linestyle="none", markersize=12, markeredgewidth=2.2, color=theme.ink_primary,
               label="Overall score after the season")
    ])
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.45, -0.075), ncols=len(handles),
              frameon=False, handlelength=1.2, columnspacing=1.2)
    boss = meta.get("boss_en") if isinstance(meta.get("boss_en"), str) else "?"
    _frame(fig, ax, theme, title=f"Season {season} tiers",
           subtitle=[f"{boss} · weak to", _element_part(icons, meta.get("weak_element"), 13) or "?",
                     "· bar = lift that season (colour = tier) · beside each face = its element"])
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def chart_trajectories(history: pd.DataFrame, current: pd.DataFrame, theme: th.Theme, out: Path, names: Names,
                       icons: Icons, *, unit_ids: list[str]) -> Path | None:
    """Selected units, season by season: the season's lift and the overall score as it stood."""
    if history.empty or not unit_ids:
        return None
    config = load_tier_config()
    cols = 2
    rows_n = int(np.ceil(len(unit_ids) / cols))
    fig, axes = plt.subplots(rows_n, cols, figsize=(12, 3.0 * rows_n + 0.9), sharex=True, sharey=True)
    axes = np.atleast_1d(axes).ravel()
    s_min, s_max = int(history["season"].min()), int(history["season"].max())
    ymax = max(2.3, float(history.loc[history["unit_id"].isin(unit_ids), "lift"].max()) * 1.05)
    best = current.set_index("unit_id")["best_element"] if not current.empty else pd.Series(dtype=str)
    live = history.loc[~history["final"].astype(str).str.lower().isin(("true", "1")), "season"]
    for ax, unit_id in zip(axes, unit_ids):
        unit = history[history["unit_id"] == unit_id].sort_values("season")
        if unit.empty:
            ax.set_visible(False)
            continue
        info = unit.iloc[-1]
        for label, cut in config.cuts[:-1]:
            ax.axhline(cut, color=theme.grid, linewidth=1, zorder=1)
            ax.annotate(label, (s_max + 0.6, cut), fontsize=8, color=theme.ink_muted, va="bottom", annotation_clip=False)
        for season in live:
            ax.axvspan(season - 0.5, season + 0.5, color=theme.page, zorder=0)
        seasons_x = unit["season"].astype(int)
        ax.plot(seasons_x, unit["lift"], color=theme.categorical[0], linewidth=1.0, zorder=2)
        favoured = unit["weak_element"] == best.get(unit_id, "")
        ax.scatter(seasons_x[~favoured], unit.loc[~favoured, "lift"], s=30, facecolor=theme.surface,
                   edgecolor=theme.categorical[0], linewidth=1.4, zorder=3)
        ax.scatter(seasons_x[favoured], unit.loc[favoured, "lift"], s=38, color=theme.categorical[0],
                   edgecolor=theme.surface, linewidth=1.2, zorder=4)
        ax.plot(seasons_x, unit["overall"], color=theme.categorical[1], linewidth=2.0, zorder=5,
                solid_capstyle="round", solid_joinstyle="round")
        ax.set_xlim(s_min - 0.8, s_max + 0.8)
        ax.set_ylim(-0.08, ymax)
        ax.grid(False)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        best_el = best.get(unit_id, "")
        face = icons.face(unit_id)
        klass = icons.unit_class(info.get("unit_class"))
        parts = [(face, 30) if face is not None else names(info),
                 _element_part(icons, info.get("element"), 17),
                 (klass, 15) if klass is not None else str(info.get("unit_class", "") or "")]
        if isinstance(best_el, str) and best_el:
            parts += ["·  best when the boss is weak to", _element_part(icons, best_el, 14)]
        place(ax, line(parts, height_pt=14, fontsize=10, color=theme.ink_secondary, sep_pt=4), (0, 1),
              xycoords="axes fraction", offset=(0, 6), align=(0, 0))
    for ax in axes[len(unit_ids):]:
        ax.set_visible(False)
    for ax in axes[-cols:]:
        ax.set_xlabel("Solo Raid season")
    for ax in axes[::cols]:
        ax.set_ylabel("Lift")
    handles = [
        Line2D([], [], color=theme.categorical[0], linewidth=1.0, marker="o", markersize=6,
               markerfacecolor=theme.categorical[0], markeredgecolor=theme.surface,
               label="Season lift · filled = boss weak to the unit's best element"),
        Line2D([], [], color=theme.categorical[1], linewidth=2.0, label="Overall score as it stood"),
    ]
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.045, 0.935), ncols=2, frameon=False)
    fig.text(0.05, 1.005, "How these units' tiers moved", fontsize=14, fontweight="bold",
             color=theme.ink_primary, ha="left", va="bottom")
    cuts = " · ".join(f"{label} {cut:g}" for label, cut in config.cuts[:-1])
    fig.text(0.05, 0.982, f"Gridlines = tier cuts ({cuts}) · shaded column = season in progress",
             fontsize=9, color=theme.ink_muted, ha="left", va="bottom")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def chart_tier_heatmap(history: pd.DataFrame, theme: th.Theme, out: Path, names: Names, icons: Icons,
                       *, min_seasons: int = 3) -> Path | None:
    """Units that reached S in at least ``min_seasons`` seasons, by release, against every season."""
    if history.empty:
        return None
    config = load_tier_config()
    order = config.tier_order
    strong = history[history["lift"] >= config.cut("S")].groupby("unit_id").size()
    ids = strong[strong >= min_seasons].index
    if len(ids) == 0:
        return None
    units = history[history["unit_id"].isin(ids)].drop_duplicates("unit_id").sort_values(["release_date", "unit_id"])
    seasons = season_order(history["season"].dropna())
    column = {s: i for i, s in enumerate(seasons)}
    weak = history.drop_duplicates("season").set_index("season")["weak_element"]
    live = set(history.loc[~history["final"].astype(str).str.lower().isin(("true", "1")), "season"].astype(int))
    n_rows, n_cols = len(units), len(seasons)
    fig, ax = plt.subplots(figsize=(0.3 * n_cols + 1.6, 0.3 * n_rows + 2.2))
    ax.set_xlim(-0.5, n_cols - 0.5)
    ax.set_ylim(n_rows - 0.5, -1.9)
    gap = 0.07
    for r, unit in enumerate(units.itertuples()):
        cells = history[history["unit_id"] == unit.unit_id]
        for cell in cells.itertuples():
            ax.add_patch(Rectangle((column[int(cell.season)] - 0.5 + gap, r - 0.5 + gap), 1 - 2 * gap, 1 - 2 * gap,
                                   facecolor=_tier_color(cell.tier, theme, order), linewidth=0, zorder=2))
    for s in seasons:
        image = icons.element(weak.get(s, ""))
        if image is not None:
            place(ax, line([image], height_pt=13, fontsize=7, color=theme.ink_secondary), (column[s], -1.05),
                  xycoords="data")
        else:
            ax.annotate(ELEMENT_INITIAL.get(weak.get(s, ""), ""), (column[s], -1.05), ha="center", va="center",
                        fontsize=7, color=theme.ink_secondary, annotation_clip=False)
    ax.annotate("boss weak to", (-0.9, -1.05), ha="right", va="center", fontsize=7.5, color=theme.ink_muted,
                annotation_clip=False)
    _label_rows(ax, theme, [_unit_parts(icons, names, u._asdict(), 19) for u in units.itertuples()], face_pt=19)
    ax.set_xticks(range(n_cols))
    ax.set_xticklabels([f"{s}*" if s in live else str(s) for s in seasons], fontsize=7)
    ax.tick_params(length=0)
    ax.grid(False)
    for side in ax.spines.values():
        side.set_visible(False)
    ax.set_xlabel("Solo Raid season  (* = in progress)")
    handles = _tier_legend(order, theme, extra=[
        Patch(facecolor=theme.surface, edgecolor=theme.axis, linewidth=0.8, label="blank = not released")
    ])
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.06), ncols=len(handles),
              frameon=False, handlelength=1.2)
    _frame(fig, ax, theme, title=f"Every season's tiers — units at S or better in {min_seasons}+ seasons",
           subtitle="Rows by release date · top row = the element each season's boss was weak to "
                    "· beside each face = the unit's own element")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def chart_element_tiers(current: pd.DataFrame, theme: th.Theme, out: Path, names: Names, icons: Icons,
                        *, limit: int = 40) -> Path | None:
    """What each unit is worth against each boss weakness, and overall, as of the newest data."""
    if current.empty:
        return None
    config = load_tier_config()
    order = config.tier_order
    table = current[current["role"] != "outside"].sort_values(["overall", "unit_id"], ascending=[False, True]).head(limit)
    if table.empty:
        return None
    columns = list(ELEMENTS) + ["overall"]
    n_rows = len(table)
    fig, ax = plt.subplots(figsize=(7.4, 0.32 * n_rows + 2.4))
    ax.set_xlim(-0.5, len(columns) - 0.5 + 0.25)
    ax.set_ylim(n_rows - 0.5, -1.75)
    gap = 0.07
    role_short = {"universal": "U", "hybrid": "H", "specialist": "S", "undetermined": "?", "outside": "-"}
    for r, (_, row) in enumerate(table.iterrows()):
        for c, element in enumerate(columns):
            x = c + (0.25 if element == "overall" else 0.0)
            if element == "overall":
                tier, observed = row["overall_tier"], not bool(row["provisional"])
            else:
                slot = element.lower()
                tier, observed = row[f"tier_{slot}"], row[f"n_{slot}"] > 0
            if observed:
                ax.add_patch(Rectangle((x - 0.5 + gap, r - 0.5 + gap), 1 - 2 * gap, 1 - 2 * gap,
                                       facecolor=_tier_color(tier, theme, order), linewidth=0, zorder=2))
                # The three strongest steps are dark on light and pale on dark: flip the ink.
                strong = tier in order[:3]
                ink = (theme.page if theme.name == "dark" else "#ffffff") if strong else theme.ink_primary
            else:
                ax.add_patch(Rectangle((x - 0.5 + gap, r - 0.5 + gap), 1 - 2 * gap, 1 - 2 * gap,
                                       facecolor=theme.surface, edgecolor=theme.axis, linewidth=0.8, zorder=2))
                ink = theme.ink_muted
            ax.annotate(f"{tier}" + ("" if observed else "?"), (x, r), ha="center", va="center", fontsize=7.5,
                        color=ink, zorder=3)
    _label_rows(ax, theme, [_unit_parts(icons, names, r, 20) + [role_short.get(r["role"], "?")]
                            for _, r in table.iterrows()], face_pt=20)
    # Column heads: the element the boss is weak to, as its icon.
    header = -1.12
    for c, element in enumerate(columns):
        x = c + (0.25 if element == "overall" else 0.0)
        image = icons.element(element) if element != "overall" else None
        if image is not None:
            place(ax, line([image], height_pt=18, fontsize=8.5, color=theme.ink_secondary), (x, header),
                  xycoords="data")
        else:
            label = "Overall" if element == "overall" else f"{ELEMENT_SHORT[element]}-weak"
            ax.annotate(label, (x, header), ha="center", va="center", fontsize=8.5, color=theme.ink_secondary,
                        annotation_clip=False)
    ax.annotate("boss weak to", (-0.62, header), ha="right", va="center", fontsize=7.5, color=theme.ink_muted,
                annotation_clip=False)
    ax.set_xticks([])
    ax.tick_params(length=0)
    ax.grid(False)
    for side in ax.spines.values():
        side.set_visible(False)
    handles = _tier_legend(order, theme, extra=[
        Patch(facecolor=theme.surface, edgecolor=theme.axis, linewidth=0.8, label="? = not yet observed")
    ])
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.02), ncols=4, frameon=False,
              handlelength=1.2)
    _frame(fig, ax, theme, title="Element tiers — worth against each boss weakness",
           subtitle=f"Recent seasons weigh more (half-life {config.half_life_days:g} days) · "
                    "letter after each face = role: U universal, H hybrid, S specialist, ? undetermined")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def chart_tier_distribution(history: pd.DataFrame, theme: th.Theme, out: Path) -> Path | None:
    """How many units reach each tier, season by season (D - outside the meta - left out)."""
    if history.empty:
        return None
    order = load_tier_config().tier_order
    shown = order[:-1]
    seasons = season_order(history["season"].dropna())
    counts = history.groupby(["season", "tier"]).size().unstack(fill_value=0).reindex(seasons).fillna(0)
    for tier in shown:
        if tier not in counts.columns:
            counts[tier] = 0
    counts = counts[shown]
    fig, ax = plt.subplots(figsize=(9, 4.8))
    x = range(len(seasons))
    bottom = [0.0] * len(seasons)
    for tier in shown:
        values = counts[tier].tolist()
        ax.bar(list(x), values, bottom=bottom, width=0.62, color=_tier_color(tier, theme, order),
               edgecolor=theme.surface, linewidth=1.5, label=tier, zorder=2)
        bottom = [b + v for b, v in zip(bottom, values)]
    ax.set_xticks(list(x))
    ax.set_xticklabels([str(s) for s in seasons], fontsize=7)
    ax.set_xlabel("Season")
    ax.set_ylabel("Units")
    th.strip_chrome(ax)
    handles, labels = ax.get_legend_handles_labels()
    _frame(fig, ax, theme, title="How many units reach each tier",
           subtitle="Fixed lift cuts, so a season with one dominant deck has more SS than a spread-out one")
    ax.legend(handles[::-1], labels[::-1], loc="upper center", bbox_to_anchor=(0.5, -0.14), ncols=len(shown),
              frameon=False)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


# --------------------------------------------------------------------------
# meta movement
# --------------------------------------------------------------------------

def chart_meta_shift(shift: pd.DataFrame, theme: th.Theme, out: Path) -> Path | None:
    """Two shares on one axis: how far the meta moved, and how much of that was
    brand-new units rather than reshuffling of existing ones."""
    if shift.empty:
        return None
    labels = [f"{a}→{b}" for a, b in zip(shift["season_from"], shift["season_to"])]
    x = range(len(labels))
    fig, ax = plt.subplots(figsize=(11, 4.6))
    series = [
        ("Meta shift (total variation)", shift["total_variation"], theme.categorical[0]),
        ("Share taken by units unused the season before", shift["newcomer_share"], theme.categorical[1]),
    ]
    for label, values, color in series:
        ax.plot(list(x), values, color=color, marker="o", markersize=4, label=label, zorder=3)
        ax.annotate(f"{values.iloc[-1]:.0%}", (len(labels) - 1, values.iloc[-1]), textcoords="offset points",
                    xytext=(8, 0), color=theme.ink_secondary, fontsize=9, va="center")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=60, ha="right", fontsize=7)
    ax.set_ylim(bottom=0)
    ax.margins(x=0.03)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    th.strip_chrome(ax)
    _frame(fig, ax, theme, title="How much the meta moved each season",
           subtitle="Share of the top players' damage that changed hands between consecutive seasons", legend_cols=2)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def chart_patch_impact(impact: pd.DataFrame, theme: th.Theme, out: Path) -> Path | None:
    """Meta movement per patch window, annotated with how many units launched."""
    if impact.empty:
        return None
    labels = [f"{a}→{b}" for a, b in zip(impact["season_from"], impact["season_to"])]
    values = impact["total_variation"].tolist()
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.set_xlim(-0.6, len(labels) - 0.4)
    ax.set_ylim(0, max(values) * 1.25 if values else 1)
    th.rounded_bars(ax, list(range(len(labels))), values, color=theme.accent)
    for i, (value, released) in enumerate(zip(values, impact["units_released"])):
        if released:
            ax.annotate(f"+{int(released)}", (i, value), textcoords="offset points", xytext=(0, 4), ha="center",
                        fontsize=7.5, color=theme.ink_secondary)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=60, ha="right", fontsize=7)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    th.strip_chrome(ax)
    _frame(fig, ax, theme, title="Meta movement per patch window",
           subtitle="Total variation between consecutive seasons · +n = units released in the window")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


# --------------------------------------------------------------------------

def default_units(current: pd.DataFrame, top_n: int) -> list[str]:
    """The strongest settled units right now, one per slot."""
    if current.empty:
        return []
    settled = current[~current["provisional"].astype(str).str.lower().isin(("true", "1"))]
    return settled.sort_values(["overall", "unit_id"], ascending=[False, True])["unit_id"].head(top_n).tolist()


def resolve_units(queries: list[str], history: pd.DataFrame) -> list[str]:
    from ..util.names import normalize_name

    units = history.drop_duplicates("unit_id")
    found = []
    for query in queries:
        key = normalize_name(query)
        match = units[(units["name_ko"].map(normalize_name) == key) | (units["name_en"].map(normalize_name) == key)
                      | (units["unit_id"] == query)]
        if match.empty:
            raise LookupError(f"no unit named {query!r} in the ranking data")
        found.append(str(match["unit_id"].iloc[0]))
    return found


def render_all(
    *,
    data_dir: Path | None = None,
    out_dir: Path | None = None,
    themes: tuple[str, ...] = ("light", "dark"),
    top_n: int = 6,
    units: list[str] | None = None,
    sample: str = "",
    icons_dir: Path | None = None,
) -> dict[str, Any]:
    """Every chart from the metric tables in ``data_dir``, into ``out_dir``.

    ``sample`` names a server sample other than the configured one; it is
    appended to every subtitle. ``icons_dir`` defaults to ``data/assets/icons``.
    """
    global _sample_caption
    directory = data_dir or processed_dir()
    target = out_dir or reports_dir()
    target.mkdir(parents=True, exist_ok=True)

    history = _read("metrics_unit_season.csv", directory)
    seasons = _read("metrics_seasons.csv", directory)
    current = _read("metrics_element_tiers.csv", directory)
    shift = _read("metrics_meta_shift.csv", directory)
    impact = _read("metrics_patch_impact.csv", directory)
    if history.empty and shift.empty:
        raise RuntimeError("no metric tables found; run `nikke analyze` first")
    picks = resolve_units(units, history) if units else default_units(current, top_n)

    names = Names()
    named_units: set[str] = set()
    written: list[str] = []
    skipped: list[str] = []
    _sample_caption = sample
    try:
        for theme_name in themes:
            theme = th.THEMES[theme_name]
            th.apply(theme)
            icons = Icons(theme, icons_dir)
            suffix = "" if theme_name == "light" else "-dark"
            jobs = [
                ("tier-snapshot", lambda p, t=theme, i=icons: chart_tier_snapshot(history, seasons, t, p, names, i)),
                ("tier-trajectories",
                 lambda p, t=theme, i=icons: chart_trajectories(history, current, t, p, names, i, unit_ids=picks)),
                ("tier-heatmap", lambda p, t=theme, i=icons: chart_tier_heatmap(history, t, p, names, i)),
                ("element-tiers", lambda p, t=theme, i=icons: chart_element_tiers(current, t, p, names, i)),
                ("tier-distribution", lambda p, t=theme: chart_tier_distribution(history, t, p)),
                ("meta-shift", lambda p, t=theme: chart_meta_shift(shift, t, p)),
                ("patch-impact", lambda p, t=theme: chart_patch_impact(impact, t, p)),
            ]
            for name, render in jobs:
                path = target / f"{name}{suffix}.png"
                result = render(path)
                (written if result else skipped).append(f"{name}{suffix}")
            named_units |= icons.named_units
    finally:
        _sample_caption = ""

    log.info("rendered %s charts -> %s", len(written), target)
    if named_units:
        log.warning("no icon for %s unit(s), drawn by name: %s (run `nikke collect icons`)",
                    len(named_units), ", ".join(sorted(named_units)))
    return {"out_dir": str(target), "written": written, "skipped_no_data": sorted(set(skipped)),
            "korean_names": names.korean, "named_units": sorted(named_units)}
