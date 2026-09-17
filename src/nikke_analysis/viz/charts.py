"""Render the metric tables as charts.

Five charts, each answering one question:

``meta_shift``           how much did the meta move, season to season?
``usage_trend``          which units are rising and falling?
``tier_distribution``    how is the roster spread across tiers over time?
``usage_vs_performance`` popular versus actually effective, this season
``patch_impact``         which patch windows moved the meta most?

Every chart is rendered in both light and dark. The dark version uses its own
validated steps rather than an inverted copy of the light one.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # no display in CI or a cloud session
import matplotlib.pyplot as plt
import pandas as pd

from ..analyze.metrics import season_order
from ..analyze.tiers import load_tier_config
from ..paths import processed_dir, reports_dir
from . import theme as th

log = logging.getLogger(__name__)


SEASON_COLUMNS = ("season", "season_from", "season_to")


def _read(name: str, directory: Path) -> pd.DataFrame:
    """Read a metric table, forcing season columns to strings.

    A CSV round-trip turns season "7" into the integer 7, which then silently
    fails to match the string season order and renders an empty chart. Casting
    on the way in is the one place that can go wrong, so it goes here.
    """
    path = directory / name
    if not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame()
    frame = pd.read_csv(path)
    for column in SEASON_COLUMNS:
        if column in frame.columns:
            frame[column] = frame[column].astype(str)
    return frame


def _label_unit(row: pd.Series) -> str:
    return str(row.get("name_en") or row.get("name_ko") or row.get("unit_id"))


def _frame(
    fig,
    ax,
    theme: th.Theme,
    *,
    title: str,
    subtitle: str = "",
    legend_cols: int = 0,
) -> None:
    """Title, subtitle and legend in one place, positioned in points.

    Axes-fraction positioning collides as soon as a chart is resized, so both
    lines are offset from the axes in typographic points and the legend sits
    below the plot where it can never overlap a mark.
    """
    ax.set_title("")
    ax.annotate(
        title,
        (0, 1),
        xycoords="axes fraction",
        textcoords="offset points",
        xytext=(0, 34),
        fontsize=14,
        fontweight="bold",
        color=theme.ink_primary,
        va="bottom",
        annotation_clip=False,
    )
    if subtitle:
        ax.annotate(
            subtitle,
            (0, 1),
            xycoords="axes fraction",
            textcoords="offset points",
            xytext=(0, 16),
            fontsize=9,
            color=theme.ink_muted,
            va="bottom",
            annotation_clip=False,
        )
    if legend_cols:
        ax.legend(
            loc="upper center",
            bbox_to_anchor=(0.5, -0.16),
            ncols=legend_cols,
            frameon=False,
        )


# --------------------------------------------------------------------------
# charts
# --------------------------------------------------------------------------

def chart_meta_shift(shift: pd.DataFrame, theme: th.Theme, out: Path) -> Path | None:
    """Two shares on one axis: how far the meta moved, and how much of that was
    brand-new units rather than reshuffling of existing ones."""
    if shift.empty:
        return None
    labels = [f"{a}→{b}" for a, b in zip(shift["season_from"], shift["season_to"])]
    x = range(len(labels))

    fig, ax = plt.subplots(figsize=(9, 4.6))
    series = [
        ("Meta shift (total variation)", shift["total_variation"], theme.categorical[0]),
        ("Share taken by new units", shift["newcomer_share"], theme.categorical[1]),
    ]
    for label, values, color in series:
        ax.plot(list(x), values, color=color, marker="o", markersize=5, label=label, zorder=3)
        if len(labels):
            ax.annotate(
                f"{values.iloc[-1]:.0%}",
                (len(labels) - 1, values.iloc[-1]),
                textcoords="offset points",
                xytext=(8, 0),
                color=theme.ink_secondary,
                fontsize=9,
                va="center",
            )

    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylim(bottom=0)
    ax.margins(x=0.06)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    th.strip_chrome(ax)
    _frame(
        fig,
        ax,
        theme,
        title="How much the meta moved each season",
        subtitle="Rank-weighted usage share; 20% means a fifth of the meta changed hands",
        legend_cols=2,
    )
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def chart_usage_trend(
    tiers_table: pd.DataFrame, theme: th.Theme, out: Path, *, top_n: int = 6
) -> Path | None:
    """Rank-weighted pick rate over time for the units that matter now."""
    if tiers_table.empty:
        return None
    seasons = season_order(tiers_table["season"])
    latest = tiers_table[tiers_table["season"].astype(str) == seasons[-1]]
    top_units = latest.nlargest(min(top_n, len(latest)), "weighted_pick_rate")["unit_id"].tolist()
    if not top_units:
        return None

    fig, ax = plt.subplots(figsize=(9.5, 5))
    position = {s: i for i, s in enumerate(seasons)}
    ends: list[tuple[float, str, str]] = []
    for slot, unit_id in enumerate(top_units):
        rows = tiers_table[tiers_table["unit_id"] == unit_id].copy()
        rows["x"] = rows["season"].astype(str).map(position)
        rows = rows.sort_values("x")
        color = theme.categorical[slot % len(theme.categorical)]
        label = _label_unit(rows.iloc[-1])
        ax.plot(
            rows["x"],
            rows["weighted_pick_rate"],
            color=color,
            marker="o",
            markersize=4,
            label=label,
            zorder=3,
        )
        ends.append((float(rows["weighted_pick_rate"].iloc[-1]), label, color))

    ax.set_xticks(range(len(seasons)))
    ax.set_xticklabels(seasons)
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_xlabel("Season")
    th.strip_chrome(ax)
    ax.margins(x=0.16)

    # Direct end labels are the required relief for the low-contrast slots, so
    # they must not stack on top of each other when series finish close together.
    span = ax.get_ylim()[1] - ax.get_ylim()[0]
    placed = th.spread_labels([value for value, _, _ in ends], span * 0.045)
    for (value, label, color), y in zip(ends, placed):
        ax.annotate(
            label,
            xy=(len(seasons) - 1, value),
            xytext=(len(seasons) - 1 + 0.18, y),
            fontsize=9,
            color=theme.ink_secondary,
            va="center",
            annotation_clip=False,
            arrowprops=dict(arrowstyle="-", color=theme.grid, linewidth=0.8, shrinkA=0, shrinkB=2),
        )

    _frame(
        fig,
        ax,
        theme,
        title=f"Top {len(top_units)} units by current usage",
        subtitle="Rank-weighted pick rate inside the top-50 leaderboard",
        legend_cols=min(len(top_units), 3),
    )
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def chart_tier_distribution(tiers_table: pd.DataFrame, theme: th.Theme, out: Path) -> Path | None:
    """How many units sit in each tier, season by season."""
    if tiers_table.empty:
        return None
    config = load_tier_config()
    order = config.tier_order
    seasons = season_order(tiers_table["season"])
    counts = (
        tiers_table.groupby(["season", "tier"]).size().unstack(fill_value=0).reindex(seasons)
    )
    for tier in order:
        if tier not in counts.columns:
            counts[tier] = 0
    counts = counts[order]

    fig, ax = plt.subplots(figsize=(9, 4.8))
    x = range(len(seasons))
    bottom = [0.0] * len(seasons)
    gap = 1.5  # points; a surface-coloured hairline reads as the 2px spacer
    for tier in order:
        values = counts[tier].tolist()
        ax.bar(
            list(x),
            values,
            bottom=bottom,
            width=0.62,
            color=th.tier_color(tier, theme, order),
            edgecolor=theme.surface,
            linewidth=gap,
            label=tier,
            zorder=2,
        )
        bottom = [b + v for b, v in zip(bottom, values)]

    ax.set_xticks(list(x))
    ax.set_xticklabels(seasons)
    ax.set_xlabel("Season")
    ax.set_ylabel("Units")
    th.strip_chrome(ax)
    handles, labels = ax.get_legend_handles_labels()
    _frame(
        fig,
        ax,
        theme,
        title="Tier distribution over time",
        subtitle="Every unit available that season, including the never-picked",
    )
    ax.legend(
        handles[::-1],
        labels[::-1],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.14),
        ncols=len(order),
        frameon=False,
    )
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def chart_usage_vs_performance(
    tiers_table: pd.DataFrame, theme: th.Theme, out: Path, *, label_n: int = 10
) -> Path | None:
    """Popularity against measured contribution, for the newest season.

    The interesting units are off the diagonal: heavily used with no score edge
    (fashion or a comfort pick), or a strong edge at low usage (underrated, or
    gated behind investment).
    """
    if tiers_table.empty:
        return None
    seasons = season_order(tiers_table["season"])
    latest = tiers_table[tiers_table["season"].astype(str) == seasons[-1]].copy()
    latest = latest[latest["weighted_pick_rate"] > 0]
    if latest.empty:
        return None

    fig, ax = plt.subplots(figsize=(8.4, 5.6))
    ax.axhline(0, color=theme.axis, linewidth=1, zorder=1)
    ax.scatter(
        latest["weighted_pick_rate"],
        latest["score_delta"],
        s=60,
        color=theme.accent,
        edgecolor=theme.surface,
        linewidth=1.2,
        alpha=0.9,
        zorder=3,
    )
    # Label only the units worth naming, and push the labels apart vertically so
    # a cluster of similar performers stays readable.
    labelled = latest.nlargest(min(label_n, len(latest)), "weighted_pick_rate")
    span = float(latest["score_delta"].max() - latest["score_delta"].min()) or 1.0
    placed = th.spread_labels(labelled["score_delta"].astype(float).tolist(), span * 0.06)
    for (_, row), y in zip(labelled.iterrows(), placed):
        ax.annotate(
            _label_unit(row),
            xy=(row["weighted_pick_rate"], row["score_delta"]),
            xytext=(row["weighted_pick_rate"], y),
            textcoords="data",
            fontsize=8.5,
            color=theme.ink_secondary,
            va="center",
            ha="left",
            arrowprops=dict(arrowstyle="-", color=theme.grid, linewidth=0.8, shrinkA=0, shrinkB=6),
        )

    ax.set_xlabel("Rank-weighted pick rate")
    ax.set_ylabel("Score delta (teams with − teams without)")
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.1%}")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(True)
    _frame(
        fig,
        ax,
        theme,
        title=f"Usage vs. measured contribution \u2014 season {seasons[-1]}",
        subtitle="Above the line: teams running this unit score higher than those that don't",
    )
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def chart_patch_impact(impact: pd.DataFrame, theme: th.Theme, out: Path) -> Path | None:
    """Meta movement per patch window, annotated with how many units launched."""
    if impact.empty:
        return None
    labels = [f"{a}→{b}" for a, b in zip(impact["season_from"], impact["season_to"])]
    values = impact["total_variation"].tolist()

    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.set_xlim(-0.6, len(labels) - 0.4)
    ax.set_ylim(0, max(values) * 1.25 if values else 1)
    th.rounded_bars(ax, list(range(len(labels))), values, color=theme.accent)

    for i, (value, released) in enumerate(zip(values, impact["units_released"])):
        ax.annotate(
            f"{value:.0%}" + (f"  ·  +{int(released)} new" if released else ""),
            (i, value),
            textcoords="offset points",
            xytext=(0, 6),
            ha="center",
            fontsize=8.5,
            color=theme.ink_secondary,
        )

    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    th.strip_chrome(ax)
    _frame(
        fig,
        ax,
        theme,
        title="Meta movement per patch window",
        subtitle="Total variation of rank-weighted usage between consecutive seasons",
    )
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


# --------------------------------------------------------------------------

def render_all(
    *,
    data_dir: Path | None = None,
    out_dir: Path | None = None,
    themes: tuple[str, ...] = ("light", "dark"),
    top_n: int = 6,
) -> dict[str, Any]:
    directory = data_dir or processed_dir()
    target = out_dir or reports_dir()
    target.mkdir(parents=True, exist_ok=True)

    shift = _read("metrics_meta_shift.csv", directory)
    tiers_table = _read("metrics_tiers.csv", directory)
    impact = _read("metrics_patch_impact.csv", directory)
    if tiers_table.empty and shift.empty:
        raise RuntimeError("no metric tables found; run `nikke analyze` first")

    written: list[str] = []
    skipped: list[str] = []
    for theme_name in themes:
        theme = th.THEMES[theme_name]
        th.apply(theme)
        suffix = "" if theme_name == "light" else "-dark"
        jobs = [
            ("meta-shift", lambda p, t=theme: chart_meta_shift(shift, t, p)),
            ("usage-trend", lambda p, t=theme: chart_usage_trend(tiers_table, t, p, top_n=top_n)),
            ("tier-distribution", lambda p, t=theme: chart_tier_distribution(tiers_table, t, p)),
            ("usage-vs-performance", lambda p, t=theme: chart_usage_vs_performance(tiers_table, t, p)),
            ("patch-impact", lambda p, t=theme: chart_patch_impact(impact, t, p)),
        ]
        for name, render in jobs:
            path = target / f"{name}{suffix}.png"
            result = render(path)
            (written if result else skipped).append(f"{name}{suffix}")

    log.info("rendered %s charts -> %s", len(written), target)
    return {"out_dir": str(target), "written": written, "skipped_no_data": sorted(set(skipped))}
