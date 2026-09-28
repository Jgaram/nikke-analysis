"""Chart tokens and matplotlib styling.

Colours are roles, not decoration, and each role is fixed here so every chart in
the repo reads as one system. Both modes are selected rather than flipped: the
dark values are their own steps against the dark surface.

The palettes below were checked with the data-viz validator rather than picked by
eye:

* categorical slots 1-6, adjacent pairs - worst CVD deltaE 9.1, worst
  normal-vision deltaE 19.6. Three light slots fall under 3:1 against the
  surface, so every chart using them ships visible direct labels.
* the ordinal tier ramp is five steps of one hue with monotone lightness and
  adjacent gaps >= 0.06. Six steps do not fit the usable range, so the bottom
  tier - "outside the meta" - takes the neutral instead of a sixth blue, which
  is also what it means.
"""

from __future__ import annotations

from dataclasses import dataclass

import matplotlib


@dataclass(frozen=True)
class Theme:
    name: str
    surface: str
    page: str
    ink_primary: str
    ink_secondary: str
    ink_muted: str
    grid: str
    axis: str
    categorical: tuple[str, ...]
    # Ordered weakest -> strongest *against this surface*: pale blue to deep blue
    # on light, deep blue to pale blue on dark. Both directions were validated
    # against their own surface rather than flipped from each other.
    ordinal: tuple[str, ...]
    neutral: str
    accent: str


LIGHT = Theme(
    name="light",
    surface="#fcfcfb",
    page="#f9f9f7",
    ink_primary="#0b0b0b",
    ink_secondary="#52514e",
    ink_muted="#898781",
    grid="#e1e0d9",
    axis="#c3c2b7",
    categorical=("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"),
    ordinal=("#86b6ef", "#3987e5", "#256abf", "#184f95", "#0d366b"),
    neutral="#c3c2b7",
    accent="#2a78d6",
)

DARK = Theme(
    name="dark",
    surface="#1a1a19",
    page="#0d0d0d",
    ink_primary="#ffffff",
    ink_secondary="#c3c2b7",
    ink_muted="#898781",
    grid="#2c2c2a",
    axis="#383835",
    categorical=("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"),
    ordinal=("#184f95", "#256abf", "#3987e5", "#6da7ec", "#b7d3f6"),
    neutral="#383835",
    accent="#3987e5",
)

THEMES = {"light": LIGHT, "dark": DARK}

FONT_STACK = ["DejaVu Sans", "Noto Sans CJK KR", "Noto Sans KR", "sans-serif"]

# Fonts that carry Hangul, in order of preference. Unit names are drawn in
# Korean when one of these is installed and in English otherwise, so a machine
# without them still renders readable charts instead of empty boxes.
HANGUL_FONTS = (
    "Noto Sans CJK KR",
    "Noto Sans KR",
    "Source Han Sans KR",
    "NanumGothic",
    "NanumBarunGothic",
    "Malgun Gothic",
    "Apple SD Gothic Neo",
    "AppleGothic",
    "WenQuanYi Zen Hei",
)


def hangul_font() -> str | None:
    """The first installed font that can draw Korean unit names, if any."""
    from matplotlib import font_manager

    installed = {f.name for f in font_manager.fontManager.ttflist}
    return next((name for name in HANGUL_FONTS if name in installed), None)


def apply(theme: Theme) -> None:
    """Set the rcParams a chart should never have to repeat."""
    korean = hangul_font()
    matplotlib.rcParams.update(
        {
            "figure.facecolor": theme.surface,
            "axes.facecolor": theme.surface,
            "savefig.facecolor": theme.surface,
            # Latin glyphs from DejaVu; Hangul falls through to the Korean font.
            "font.family": ["DejaVu Sans", korean] if korean else "sans-serif",
            "font.sans-serif": FONT_STACK,
            "axes.unicode_minus": False,
            "text.color": theme.ink_primary,
            "axes.labelcolor": theme.ink_secondary,
            "axes.edgecolor": theme.axis,
            "axes.labelsize": 10,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": theme.grid,
            "grid.linewidth": 0.8,
            "xtick.color": theme.ink_muted,
            "ytick.color": theme.ink_muted,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.frameon": False,
            "legend.fontsize": 9,
            "legend.labelcolor": theme.ink_secondary,
            "lines.linewidth": 2.0,
            "lines.markersize": 5.0,
            "figure.dpi": 140,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.3,
        }
    )


def strip_chrome(ax) -> None:
    """Recessive axes: horizontal gridlines only, no box around the plot."""
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", visible=True)
    ax.grid(axis="x", visible=False)


def tier_color(tier: str, theme: Theme, tier_order: list[str]) -> str:
    """Strongest tier gets the heaviest step; the bottom tier gets the neutral.

    The bottom tier means "outside the meta", so a neutral is the honest colour
    for it - and it keeps the blue ramp to five distinguishable steps, which is
    all one hue actually supports.
    """
    if not tier_order or tier not in tier_order or tier == tier_order[-1]:
        return theme.neutral
    position = tier_order.index(tier)  # 0 is the best tier
    steps = theme.ordinal
    index = len(steps) - 1 - min(position, len(steps) - 1)
    return steps[index]


def px_to_data(ax, pixels: float) -> tuple[float, float]:
    """How far ``pixels`` reaches in data units, on each axis.

    Corner radii and mark gaps are specified in pixels but matplotlib patches
    take data units, and the two axes almost never share a scale.
    """
    origin = ax.transData.inverted().transform((0.0, 0.0))
    offset = ax.transData.inverted().transform((pixels, pixels))
    return abs(offset[0] - origin[0]), abs(offset[1] - origin[1])


def _rounded_top_path(x: float, width: float, height: float, rx: float, ry: float):
    """A bar outline with two rounded top corners and a square base.

    Built as an explicit path in data coordinates. FancyBboxPatch would be
    shorter, but its rounding is computed in a scaled space, and with the very
    different x/y scales of a bar chart that produces visible distortion.
    """
    import numpy as np
    from matplotlib.path import Path as MplPath

    left, right = x - width / 2, x + width / 2
    rx = min(rx, width / 2)
    ry = min(ry, abs(height))
    top = height
    steps = 8

    points: list[tuple[float, float]] = [(left, 0.0), (left, top - ry)]
    angles = np.linspace(np.pi, np.pi / 2, steps)
    points += [(left + rx + rx * np.cos(a), top - ry + ry * np.sin(a)) for a in angles]
    points.append((right - rx, top))
    angles = np.linspace(np.pi / 2, 0.0, steps)
    points += [(right - rx + rx * np.cos(a), top - ry + ry * np.sin(a)) for a in angles]
    points += [(right, 0.0), (left, 0.0)]

    codes = [MplPath.MOVETO] + [MplPath.LINETO] * (len(points) - 2) + [MplPath.CLOSEPOLY]
    return MplPath(points, codes)


def rounded_bars(
    ax,
    xs,
    heights,
    *,
    color,
    width: float = 0.62,
    radius_px: float = 4.0,
) -> None:
    """Vertical bars with a 4px rounded top, anchored square to the baseline.

    The radius is converted from pixels per axis so the corner stays circular on
    screen rather than stretching with the data scale.

    ``color`` may be one colour or one per bar.
    """
    from matplotlib.patches import PathPatch

    dx, dy = px_to_data(ax, radius_px)
    colors = [color] * len(xs) if isinstance(color, str) else list(color)
    for x, height, fill in zip(xs, heights, colors):
        if height is None or height != height:  # NaN
            continue
        path = _rounded_top_path(float(x), width, float(height), dx, dy)
        ax.add_patch(PathPatch(path, facecolor=fill, linewidth=0, zorder=2))


def spread_labels(values: list[float], min_gap: float) -> list[float]:
    """Nudge overlapping end-labels apart while keeping their order.

    Direct labels are the accessibility relief for the low-contrast categorical
    slots, so they have to stay readable when several series finish at nearly the
    same value.
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    placed = list(values)
    previous = None
    for index in order:
        if previous is not None and placed[index] - previous < min_gap:
            placed[index] = previous + min_gap
        previous = placed[index]
    return placed
