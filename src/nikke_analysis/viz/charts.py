"""Render the metric tables as charts.

Each chart answers one question:

``tier-snapshot``         what was each unit's tier in the latest finished season?
``tier-trajectories``     how did these units' tiers move, season by season?
``tier-heatmap``          every strong unit's tier in every season, at a glance
``overall-tiers``         how do all units compare over the whole element rotation, now?
``element-tiers-<elem>``  how do one element's units compare in that element, now?
                          (one chart per element: ``element-tiers-fire`` ...)
``tier-distribution``     how many units reach each tier, season by season?
``meta-shift``            how much did the meta move, season to season?
``patch-impact``          which patch windows moved the meta most?

The two tier-list charts are mirror images: bars for one of a unit's two tiers,
a tick for the other, so a specialist (long bar, short overall) and a support
that carries other elements' decks (short bar, long overall) stand out.

Every chart is rendered in both light and dark. The dark version uses its own
validated steps rather than an inverted copy of the light one.

Units are drawn as their faces, and elements and burst stages as their
icons (``data/assets/icons/``, fetched by ``nikke collect icons``), so no
chart spells out a unit's name or an element. A unit whose face is not on disk
yet falls back to its Korean name, and an element without its icon to its
Korean name. Every word on a chart is Korean, so a Hangul font must be
installed (``theme.hangul_font``); without one, ``render_all`` warns.

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
from ..analyze.tiers import load_tier_config, played_with_treasure
from ..paths import processed_dir, reports_dir
from ..timeline import ELEMENT_KO
from . import theme as th
from .icons import Icons, heart, line, place

log = logging.getLogger(__name__)

SEASON_COLUMNS = ("season", "season_from", "season_to")
LIFT_AXIS = "기여도 (1.0 = 한 사람이 쓰는 25명이 대미지를 똑같이 나눴을 때의 몫)"

# The server sample when it is not the configured one ("all servers but NA");
# render_all sets it for the length of a run and every subtitle ends with it.
_sample_caption = ""
# Units whose skill adds an element (unit id -> those elements), from the tables
# of the run; every face is drawn with all its elements.
_extras: dict[str, list[str]] = {}


def _split(value: Any) -> list[str]:
    """``"Iron;Water"`` -> ``["Iron", "Water"]``; nothing for an empty or missing value."""
    return [v for v in value.split(";") if v] if isinstance(value, str) else []


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
    """A unit's Korean name; its English one only when it has none yet."""

    def __call__(self, row: Any) -> str:
        ko, en = row.get("name_ko"), row.get("name_en")
        if isinstance(ko, str) and ko:
            return ko
        if isinstance(en, str) and en:
            return en
        return str(row.get("unit_id", ""))


def _element_ko(element: Any) -> str:
    return ELEMENT_KO.get(element, element) if isinstance(element, str) and element else ""


def _frame(fig, ax, theme: th.Theme, *, title: str | list, subtitle: str | list = "", legend_cols: int = 0) -> None:
    """Title, subtitle and legend in one place, positioned in points.

    Axes-fraction positioning collides as soon as a chart is resized, so both
    lines are offset from the axes in typographic points and the legend sits
    below the plot where it can never overlap a mark. A title or subtitle given
    as a list mixes words and icons (see ``icons.line``).
    """
    ax.set_title("")
    if isinstance(title, list):
        place(ax, line(title, height_pt=17, fontsize=14, color=theme.ink_primary, weight="bold"), (0, 1),
              xycoords="axes fraction", offset=(0, 34), align=(0, 0))
    else:
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


def _tier_legend(order: list[str], theme: th.Theme, *, shown: list[str] | None = None,
                 extra: list | None = None) -> list:
    """A patch for each tier ``shown`` (default: all), coloured by its place in the full ``order``."""
    handles = [Patch(facecolor=_tier_color(t, theme, order), label=t) for t in (shown or order)]
    return handles + (extra or [])


def _element_part(icons: Icons, element: Any, height_pt: float, *, word: str = "{}") -> Any:
    """An element's icon at ``height_pt``, or the element's Korean name when there is none."""
    image = icons.element(element)
    if image is not None:
        return (image, height_pt)
    return word.format(_element_ko(element)) if isinstance(element, str) and element else ""


def _burst_part(icons: Icons, burst: Any, height_pt: float) -> Any:
    """A burst stage's numeral as its icon, or as text when there is none."""
    image = icons.burst(burst)
    if image is not None:
        return (image, height_pt)
    return burst if isinstance(burst, str) else ""


def _unit_parts(icons: Icons, names: Names, row: Any, face_pt: float, *, elements: list | None = None) -> list:
    """A unit as its face with its elements and burst stage beside it; its name
    and element names when the face is missing. ``elements`` are the element
    icons to draw: by default the unit's own and any its skill adds."""
    unit_id = str(row.get("unit_id", ""))
    if elements is None:
        elements = [row.get("element")] + _extras.get(unit_id, [])
    elements = [e for e in elements if isinstance(e, str) and e]
    face = icons.face(unit_id)
    burst = _burst_part(icons, row.get("burst"), face_pt * 0.5)
    if face is not None:
        return [(face, face_pt)] + [_element_part(icons, e, face_pt * 0.62) for e in elements] + [burst]
    tags = [_element_part(icons, e, face_pt * 0.62, word="({})") or "(?)" for e in elements]
    return [names(row)] + tags + [burst]


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

def _is_true(values: pd.Series) -> pd.Series:
    """A flag column as booleans, whether it was read back as bools or as text."""
    return values.astype(str).str.lower().isin(("true", "1"))


def _tier_bars(theme: th.Theme, table: pd.DataFrame, names: Names, icons: Icons, *, value: str, tier: str,
               ticks: list[list[float]], tick_label: str, labels: list[list] | None = None,
               starred: list[bool] | None = None, star_label: str = "", note: list | str = "",
               cuts: list[tuple[str, float]] | None = None):
    """Units as horizontal bars of ``value`` coloured by ``tier``, strongest on
    top, with ticks - the body the tier-list charts share.

    ``table`` comes weakest first; ``ticks`` holds each row's tick positions
    (none, one, or one per element). ``labels`` overrides the rows' label parts.
    A row ``starred`` gets a ``*``, explained by ``star_label`` in the legend;
    ``note`` (words and icons) goes on a line under the legend. Returns the
    figure and axes, framed and saved by the caller. ``cuts`` are the lines drawn
    (the season/element cuts by default).
    """
    config = load_tier_config()
    order = config.tier_order
    n = len(table)
    fig, ax = plt.subplots(figsize=(9.2, 0.34 * n + 1.8))
    points = [(float(x), y) for y, xs in enumerate(ticks) for x in xs if x is not None and pd.notna(x)]
    reach = max([float(table[value].max())] + [x for x, _ in points])
    ax.set_xlim(0, max(2.0, reach * 1.12))
    ax.set_ylim(-0.7, n - 0.3)
    fig.canvas.draw()
    for i, (_, row) in enumerate(table.iterrows()):
        _rounded_hbar(ax, i, float(row[value]), 0.62, _tier_color(row[tier], theme, order))
    if points:
        ax.scatter([x for x, _ in points], [y for _, y in points], marker="|", s=170, linewidths=2.2,
                   color=theme.ink_primary, zorder=4)
    rows = labels if labels is not None else [_unit_parts(icons, names, r, 21) for _, r in table.iterrows()]
    if starred is not None:
        rows = [parts + (["*"] if star else []) for parts, star in zip(rows, starred)]
    _label_rows(ax, theme, rows, face_pt=21, fontsize=9)
    ax.tick_params(axis="y", length=0)
    for label, cut in (cuts or config.cuts)[:-1]:
        ax.axvline(cut, color=theme.grid, linewidth=1, zorder=1)
        ax.annotate(label, (cut, n - 0.3), textcoords="offset points", xytext=(4, 2), fontsize=9,
                    color=theme.ink_muted, va="bottom", annotation_clip=False)
    ax.grid(False)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.set_xlabel(LIFT_AXIS)
    extra = [Line2D([], [], marker="|", linestyle="none", markersize=12, markeredgewidth=2.2,
                    color=theme.ink_primary, label=tick_label)]
    if starred is not None and any(starred) and star_label:
        extra.append(Line2D([], [], linestyle="none", label=star_label))
    handles = _tier_legend(order, theme, shown=order[:-1], extra=extra)
    # Below the axis title whatever the chart's height: offset in points, not axes fractions.
    height_pt = ax.get_window_extent().height * 72.0 / fig.dpi
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.45, -48.0 / height_pt), ncols=len(handles),
              frameon=False, handlelength=1.2, columnspacing=1.2)
    if note:
        place(ax, line(note if isinstance(note, list) else [note], height_pt=11, fontsize=8.5, color=theme.ink_muted),
              (0, 0), xycoords="axes fraction", offset=(0, -76), align=(0, 1))
    return fig, ax


def _boss(meta: Any) -> str:
    """A season's boss by its Korean name, its English one when it has none."""
    for column in ("boss_ko", "boss_en"):
        value = meta.get(column)
        if isinstance(value, str) and value:
            return value
    return "?"


def _recency(config: Any) -> str:
    if config.half_life_days <= 0:
        return "모든 시즌을 똑같이 침"
    return f"최근 시즌일수록 크게 침({config.half_life_days:g}일 지난 시즌은 절반만)"


def _live_note(seasons: pd.DataFrame) -> str:
    """``진행 중 시즌 41(09/28 수집분)도 잠정으로 들어감`` when the tier tables count a season in progress."""
    if seasons.empty or not load_tier_config().include_live:
        return ""
    live = seasons[~_is_true(seasons["final"])]
    if live.empty:
        return ""
    row = live.sort_values("season").iloc[-1]
    day = pd.Timestamp(row["collected_on"]).tz_convert("Asia/Seoul") if pd.notna(row.get("collected_on")) else None
    return f"진행 중 시즌 {int(row['season'])}" + (f"({day:%m/%d} 수집분)" if day is not None else "") + "도 잠정으로 들어감"


def chart_tier_snapshot(history: pd.DataFrame, seasons: pd.DataFrame, theme: th.Theme, out: Path,
                        names: Names, icons: Icons) -> Path | None:
    """Every unit that mattered in the latest finished season, by lift and tier.

    The tick on each bar is the unit's overall tier score once that season was
    over - where a bar and its tick disagree, the season suited the unit (or
    did not) more than usual.
    """
    if history.empty or seasons.empty:
        return None
    final = seasons[_is_true(seasons["final"])]
    if final.empty:
        return None
    season = int(final["season"].max())
    meta = final[final["season"] == season].iloc[0]
    table = history[(history["season"] == season) & (history["lift"] >= load_tier_config().cut("C"))]
    table = table.sort_values(["lift", "unit_id"], ascending=[True, True])
    if table.empty:
        return None
    fig, ax = _tier_bars(theme, table, names, icons, value="lift", tier="tier", ticks=[[v] for v in table["overall"]],
                         tick_label="시즌이 끝났을 때의 종합 점수")
    boss = _boss(meta)
    _frame(fig, ax, theme, title=f"시즌 {season} 티어",
           subtitle=[f"{boss} · 약점", _element_part(icons, meta.get("weak_element"), 13) or "?",
                     "· 막대 = 그 시즌 기여도(색 = 티어) · 얼굴 옆 = 그 니케의 속성과 버스트"])
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def chart_overall_tiers(overall: pd.DataFrame, elements: pd.DataFrame, theme: th.Theme, out: Path, names: Names,
                        icons: Icons, *, limit: int = 60, live: str = "") -> Path | None:
    """Every unit worth anything overall, by overall score, with its element score as the tick
    (one tick per element for a unit whose skill adds one). ``live`` says the
    season in progress is counted.

    A tick far past its bar is a specialist; a tick short of it, a support that
    carries other elements' decks.
    """
    if overall.empty:
        return None
    config = load_tier_config()
    table = overall[overall["overall"] >= config.overall_cut("C")]
    table = table.sort_values(["overall", "unit_id"], ascending=[False, True]).head(limit).iloc[::-1]
    if table.empty:
        return None
    lifts = elements.groupby("unit_id")["element_lift"].agg(list) if not elements.empty else pd.Series(dtype=object)
    fig, ax = _tier_bars(theme, table, names, icons, value="overall", tier="overall_tier", cuts=config.overall_cuts,
                         ticks=[lifts.get(u, []) for u in table["unit_id"]],
                         tick_label="속성 티어 점수", starred=list(_is_true(table["provisional"])),
                         star_label=f"* 잠정: 겪은 보스 약점 {config.min_elements_observed}가지 미만이거나 자기 속성 못 겪음",
                         note=" · ".join(filter(None, [_recency(config), "스킬로 속성이 둘인 니케는 눈금도 둘", live])))
    _frame(fig, ax, theme, title="종합 티어 — 보스 약점 다섯 가지 전체에서",
           subtitle="막대 = 보스 약점 다섯 가지 성적의 평균(색 = 종합 티어) · 눈금 = 속성 티어 점수 · "
                    "못 겪은 약점은 겪은 다른 속성 값으로(자기 속성은 0)")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def chart_element_tiers(elements: pd.DataFrame, overall: pd.DataFrame, element: str, theme: th.Theme, out: Path,
                        names: Names, icons: Icons, *, live: str = "") -> Path | None:
    """One element's units by their score in seasons whose boss was weak to it, the overall score as the tick.

    A unit whose skill adds this element is listed too, with its own element's
    icon beside its face; a unit of this element has none (they all share it).
    ``live`` says the season in progress is counted.
    """
    if elements.empty or overall.empty:
        return None
    config = load_tier_config()
    table = elements[(elements["element"] == element) & (elements["element_lift"] >= config.cut("C"))]
    info = overall.set_index("unit_id")[["element", "burst"]].rename(columns={"element": "own_element"})
    table = table.join(info, on="unit_id").sort_values(["element_lift", "unit_id"], ascending=[True, False])
    if table.empty:
        return None
    guests = table["source"] == "skill"
    labels = [_unit_parts(icons, names, r, 21, elements=[r["own_element"]] if guest else [])
              for (_, r), guest in zip(table.iterrows(), guests)]
    icon = _element_part(icons, element, 13) or _element_ko(element)
    note = [_recency(config)]
    if guests.any():
        note += ["· 얼굴 옆 속성 아이콘 = 그 니케의 본래 속성(스킬로", icon, "우월 코드를 더한 니케)"]
    if live:
        note += [f"· {live}"]
    fig, ax = _tier_bars(theme, table, names, icons, value="element_lift", tier="element_tier",
                         ticks=[[v] for v in table["overall"]], tick_label="종합 티어 점수", labels=labels,
                         starred=list(_is_true(table["provisional"])), star_label="* 종합이 잠정", note=note)
    _frame(fig, ax, theme, title=[_element_part(icons, element, 17) or _element_ko(element), "니케끼리 비교한 속성 티어"],
           subtitle=["막대 = 보스 약점이", icon, "인 시즌의 기여도 평균(색 = 속성 티어) · 눈금 = 종합 티어 점수"])
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def _treasure_season(unit: pd.DataFrame) -> int | None:
    """The first season a unit's rows say it played with its treasure, or None."""
    played = unit.loc[played_with_treasure(unit), "season"]
    return int(played.min()) if not played.empty else None


def chart_trajectories(history: pd.DataFrame, overall: pd.DataFrame, elements: pd.DataFrame, theme: th.Theme,
                       out: Path, names: Names, icons: Icons, *, unit_ids: list[str]) -> Path | None:
    """Selected units, season by season: the season's lift and the overall score as it stood,
    with their element and overall tier now above each panel. A heart marks where a unit's
    treasure came; its overall from there stands on the seasons with it."""
    if history.empty or not unit_ids:
        return None
    config = load_tier_config()
    cols = 2
    rows_n = int(np.ceil(len(unit_ids) / cols))
    fig, axes = plt.subplots(rows_n, cols, figsize=(12, 3.0 * rows_n + 0.9), sharex=True, sharey=True)
    axes = np.atleast_1d(axes).ravel()
    s_min, s_max = int(history["season"].min()), int(history["season"].max())
    ymax = max(2.3, float(history.loc[history["unit_id"].isin(unit_ids), "lift"].max()) * 1.05)
    overall_tier = overall.set_index("unit_id")["overall_tier"] if not overall.empty else pd.Series(dtype=str)
    live = history.loc[~history["final"].astype(str).str.lower().isin(("true", "1")), "season"]
    marked = False
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
        favoured = _is_true(unit["element_match"])  # a season of the unit's element
        ax.scatter(seasons_x[~favoured], unit.loc[~favoured, "lift"], s=30, facecolor=theme.surface,
                   edgecolor=theme.categorical[0], linewidth=1.4, zorder=3)
        ax.scatter(seasons_x[favoured], unit.loc[favoured, "lift"], s=38, color=theme.categorical[0],
                   edgecolor=theme.surface, linewidth=1.2, zorder=4)
        ax.plot(seasons_x, unit["overall"], color=theme.categorical[1], linewidth=2.0, zorder=5,
                solid_capstyle="round", solid_joinstyle="round")
        treasure = _treasure_season(unit)
        if treasure is not None:
            ax.axvline(treasure - 0.5, color=theme.ink_muted, linewidth=1.0, linestyle=(0, (3, 3)), zorder=1)
            place(ax, line([heart()], height_pt=13, fontsize=8, color=theme.ink_muted), (treasure - 0.5, ymax),
                  xycoords="data", align=(0.5, 1.0))
            marked = True
        ax.set_xlim(s_min - 0.8, s_max + 0.8)
        ax.set_ylim(-0.08, ymax)
        ax.grid(False)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        parts = _unit_parts(icons, names, info, 30)
        mine = elements[elements["unit_id"] == unit_id] if not elements.empty else elements
        if not mine.empty:
            parts += ["·  속성 티어"]
            for _, standing in mine.sort_values("source", kind="stable").iterrows():
                tier = standing["element_tier"] if isinstance(standing["element_tier"], str) else "?"
                parts += [_element_part(icons, standing["element"], 14) or _element_ko(standing["element"]), tier]
        if isinstance(overall_tier.get(unit_id), str):
            parts += [f"·  종합 {overall_tier[unit_id]}"]
        place(ax, line(parts, height_pt=14, fontsize=10, color=theme.ink_secondary, sep_pt=4), (0, 1),
              xycoords="axes fraction", offset=(0, 6), align=(0, 0))
    for ax in axes[len(unit_ids):]:
        ax.set_visible(False)
    for ax in axes[-cols:]:
        ax.set_xlabel("솔로 레이드 시즌")
    for ax in axes[::cols]:
        ax.set_ylabel("기여도")
    handles = [
        Line2D([], [], color=theme.categorical[0], linewidth=1.0, marker="o", markersize=6,
               markerfacecolor=theme.categorical[0], markeredgecolor=theme.surface,
               label="시즌 기여도 · 채운 점 = 보스 약점이 그 니케의 속성인 시즌"),
        Line2D([], [], color=theme.categorical[1], linewidth=2.0, label="그 시즌이 끝났을 때의 종합 점수"),
    ]
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.045, 0.935), ncols=2, frameon=False)
    fig.text(0.05, 1.005, "니케별 티어 변화", fontsize=14, fontweight="bold",
             color=theme.ink_primary, ha="left", va="bottom")
    cuts = " · ".join(f"{label} {cut:g}" for label, cut in config.cuts[:-1])
    note = f"가로줄 = 티어 컷({cuts}) · 음영 = 진행 중 시즌(지금까지 수집분)"
    if marked:
        note += " · 하트 = 애장품이 나온 때(그 뒤 종합 점수는 애장품을 낀 시즌만으로)"
    fig.text(0.05, 0.982, note, fontsize=9, color=theme.ink_muted, ha="left", va="bottom")
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
    marked = False
    for r, unit in enumerate(units.itertuples()):
        cells = history[history["unit_id"] == unit.unit_id]
        for cell in cells.itertuples():
            ax.add_patch(Rectangle((column[int(cell.season)] - 0.5 + gap, r - 0.5 + gap), 1 - 2 * gap, 1 - 2 * gap,
                                   facecolor=_tier_color(cell.tier, theme, order), linewidth=0, zorder=2))
        treasure = _treasure_season(cells)
        if treasure is not None:
            place(ax, line([heart()], height_pt=9, fontsize=7, color=theme.ink_muted), (column[treasure] - 0.5, r),
                  xycoords="data")
            marked = True
    for s in seasons:
        image = icons.element(weak.get(s, ""))
        if image is not None:
            place(ax, line([image], height_pt=13, fontsize=7, color=theme.ink_secondary), (column[s], -1.05),
                  xycoords="data")
        else:
            ax.annotate(_element_ko(weak.get(s, ""))[:1], (column[s], -1.05), ha="center", va="center",
                        fontsize=7, color=theme.ink_secondary, annotation_clip=False)
    ax.annotate("보스 약점", (-0.9, -1.05), ha="right", va="center", fontsize=7.5, color=theme.ink_muted,
                annotation_clip=False)
    _label_rows(ax, theme, [_unit_parts(icons, names, u._asdict(), 19) for u in units.itertuples()], face_pt=19)
    ax.set_xticks(range(n_cols))
    ax.set_xticklabels([f"{s}*" if s in live else str(s) for s in seasons], fontsize=7)
    ax.tick_params(length=0)
    ax.grid(False)
    for side in ax.spines.values():
        side.set_visible(False)
    ax.set_xlabel("솔로 레이드 시즌 (* = 진행 중)")
    handles = _tier_legend(order, theme, extra=[
        Patch(facecolor=theme.surface, edgecolor=theme.axis, linewidth=0.8, label="빈칸 = 출시 전")
    ])
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.06), ncols=len(handles),
              frameon=False, handlelength=1.2)
    subtitle = ["출시 순 · 맨 윗줄 = 그 시즌 보스의 약점 속성 · 얼굴 옆 = 그 니케의 속성과 버스트"]
    if marked:
        subtitle += ["·", heart(), "= 애장품이 나온 때"]
    _frame(fig, ax, theme, title=f"시즌별 티어 — S 이상을 {min_seasons}번 이상 받은 니케", subtitle=subtitle)
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
    ax.set_xlabel("시즌")
    ax.set_ylabel("니케 수")
    th.strip_chrome(ax)
    handles, labels = ax.get_legend_handles_labels()
    _frame(fig, ax, theme, title="시즌마다 티어별 니케 수",
           subtitle="기여도에 고정 컷을 대므로, 한 덱이 압도한 시즌일수록 SS 가 많다")
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
        ("메타 변화량", shift["total_variation"], theme.categorical[0]),
        ("직전 시즌에 안 쓰인 니케가 가져간 몫", shift["newcomer_share"], theme.categorical[1]),
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
    _frame(fig, ax, theme, title="시즌마다 메타가 얼마나 바뀌었나",
           subtitle="이어진 두 시즌 사이에 다른 니케로 옮겨 간 상위권 대미지의 비율", legend_cols=2)
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
    _frame(fig, ax, theme, title="패치 구간별 메타 변화",
           subtitle="이어진 두 시즌 사이의 메타 변화량 · +n = 그 사이에 출시된 니케 수")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


# --------------------------------------------------------------------------

def default_units(overall: pd.DataFrame, top_n: int) -> list[str]:
    """The strongest settled units right now, one per slot."""
    if overall.empty:
        return []
    settled = overall[~_is_true(overall["provisional"])]
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
            raise LookupError(f"'{query}' 에 해당하는 니케가 랭킹 기록에 없다")
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
    global _sample_caption, _extras
    directory = data_dir or processed_dir()
    target = out_dir or reports_dir()
    target.mkdir(parents=True, exist_ok=True)

    history = _read("metrics_unit_season.csv", directory)
    seasons = _read("metrics_seasons.csv", directory)
    overall = _read("metrics_overall_tiers.csv", directory)
    elements = _read("metrics_element_tiers.csv", directory)
    shift = _read("metrics_meta_shift.csv", directory)
    impact = _read("metrics_patch_impact.csv", directory)
    if history.empty and shift.empty:
        raise RuntimeError("no metric tables found; run `nikke analyze` first")
    picks = resolve_units(units, history) if units else default_units(overall, top_n)

    names = Names()
    font = th.hangul_font()
    if font is None:
        log.warning("no Hangul font: the charts' Korean text will show as boxes "
                    "(install one, e.g. `sudo apt-get install fonts-nanum`)")
    live = _live_note(seasons)
    named_units: set[str] = set()
    written: list[str] = []
    skipped: list[str] = []
    _sample_caption = sample
    # The elements a unit's skill adds as of the newest data: its treasure's once it has it.
    has = _is_true(overall["treasure"]) if "treasure" in overall.columns else pd.Series(False, index=overall.index)
    _extras = {}
    for i, row in overall.iterrows():
        adds = _split(row.get("extra_elements")) + (_split(row.get("treasure_elements")) if has[i] else [])
        if adds:
            _extras[str(row["unit_id"])] = adds
    try:
        for theme_name in themes:
            theme = th.THEMES[theme_name]
            th.apply(theme)
            icons = Icons(theme, icons_dir)
            suffix = "" if theme_name == "light" else "-dark"
            jobs = [
                ("tier-snapshot", lambda p, t=theme, i=icons: chart_tier_snapshot(history, seasons, t, p, names, i)),
                ("tier-trajectories", lambda p, t=theme, i=icons: chart_trajectories(
                    history, overall, elements, t, p, names, i, unit_ids=picks)),
                ("tier-heatmap", lambda p, t=theme, i=icons: chart_tier_heatmap(history, t, p, names, i)),
                ("overall-tiers", lambda p, t=theme, i=icons: chart_overall_tiers(
                    overall, elements, t, p, names, i, live=live)),
            ] + [
                (f"element-tiers-{element.lower()}", lambda p, t=theme, i=icons, e=element: chart_element_tiers(
                    elements, overall, e, t, p, names, i, live=live))
                for element in ELEMENTS
            ] + [
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
        _sample_caption, _extras = "", {}

    log.info("rendered %s charts -> %s", len(written), target)
    if named_units:
        log.warning("no icon for %s unit(s), drawn by name: %s (run `nikke collect icons`)",
                    len(named_units), ", ".join(sorted(named_units)))
    return {"out_dir": str(target), "written": written, "skipped_no_data": sorted(set(skipped)),
            "font": font, "named_units": sorted(named_units)}
