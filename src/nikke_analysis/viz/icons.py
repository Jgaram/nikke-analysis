"""Icons in place of words: a unit's face, its element and burst stage.

A chart asks for an icon by unit id or attribute value and gets an RGBA array, or
``None`` when the file is not on disk (``nikke collect icons`` fetches them). The
chart then writes the word as before, so a unit whose face the CDN does not have
yet still reads - it is just the one row with a name in it.

Pieces are laid out with matplotlib's offset boxes, sized in points: an icon and
a fallback word sit on one baseline and stay the same size however long the
chart is.

A unit with its treasure (``221♥``) is drawn as its base's face with a heart in
the corner - the same face, marked as the other unit it counts as.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from matplotlib.colors import to_rgb
from matplotlib.offsetbox import AnnotationBbox, HPacker, OffsetImage, TextArea

from ..paths import burst_icon_path, element_icon_path, icons_dir, unit_icon_path
from ..util.names import treasure_base
from .theme import Theme

# Share of the face's side rounded off each corner - the charts' marks have
# rounded ends, and a square photo next to them looks pasted on.
FACE_CORNER = 0.14
# The treasure mark: a heart this share of the face's side, in the bottom-right
# corner, filled in this colour inside a white rim that keeps it off the face.
HEART_SHARE = 0.5
HEART_COLOR = (0.93, 0.23, 0.42)
HEART_RIM = 0.8  # the fill's size relative to the rim


def _read(path: Path) -> np.ndarray | None:
    """RGBA floats in 0..1, or None when the file is missing or unreadable.

    Only files that exist are cached, keyed by their modification time, so an
    icon fetched later in the same process is picked up.
    """
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None
    return _decode(path, stamp)


@lru_cache(maxsize=None)
def _decode(path: Path, stamp: int) -> np.ndarray | None:
    from PIL import Image

    try:
        with Image.open(path) as image:
            return np.asarray(image.convert("RGBA"), dtype=float) / 255.0
    except OSError:
        return None


def _round_corners(rgba: np.ndarray, share: float) -> np.ndarray:
    height, width = rgba.shape[:2]
    radius = share * min(height, width)
    ys, xs = np.mgrid[0:height, 0:width] + 0.5
    dx = np.maximum(0.0, np.maximum(radius - xs, xs - (width - radius)))
    dy = np.maximum(0.0, np.maximum(radius - ys, ys - (height - radius)))
    # One pixel of soft edge so the curve is not stair-stepped once scaled down.
    coverage = np.clip(radius + 0.5 - np.hypot(dx, dy), 0.0, 1.0)
    out = rgba.copy()
    out[..., 3] *= coverage
    return out


def _heart_coverage(size: int, scale: float = 1.0, samples: int = 4) -> np.ndarray:
    """How much of each pixel of a ``size`` square a centred heart covers, 0..1.

    The heart is the curve (x² + y² - 1)³ = x² y³, scaled by ``scale``;
    ``samples`` per side smooth its edge.
    """
    n = size * samples
    t = (np.arange(n) + 0.5) / n
    x = (t - 0.5) * 2.5 / scale
    y = (0.5 - t) * 2.5 / scale + 0.12  # the curve sits a little above its centre
    xs, ys = np.meshgrid(x, y)
    inside = ((xs ** 2 + ys ** 2 - 1.0) ** 3 - xs ** 2 * ys ** 3) <= 0.0
    return inside.reshape(size, samples, size, samples).mean(axis=(1, 3))


def _over(base: np.ndarray, color: tuple[float, float, float], coverage: np.ndarray) -> None:
    """Paint ``color`` over ``base`` (straight RGBA) where ``coverage`` says, in place."""
    alpha = base[..., 3]
    out_alpha = coverage + alpha * (1.0 - coverage)
    safe = np.where(out_alpha > 0, out_alpha, 1.0)
    for channel, value in enumerate(color):
        base[..., channel] = (value * coverage + base[..., channel] * alpha * (1.0 - coverage)) / safe
    base[..., 3] = out_alpha


def heart(size: int) -> np.ndarray:
    """The treasure mark on its own, ``size`` pixels square."""
    out = np.zeros((size, size, 4))
    _over(out, (1.0, 1.0, 1.0), _heart_coverage(size))
    _over(out, HEART_COLOR, _heart_coverage(size, HEART_RIM))
    return out


def with_heart(rgba: np.ndarray, share: float = HEART_SHARE) -> np.ndarray:
    """A face with the treasure mark in its bottom-right corner."""
    out = rgba.copy()
    height, width = out.shape[:2]
    size = max(1, int(round(min(height, width) * share)))
    corner = out[height - size:, width - size:]
    _over(corner, (1.0, 1.0, 1.0), _heart_coverage(size))
    _over(corner, HEART_COLOR, _heart_coverage(size, HEART_RIM))
    return out


def _pad_width(rgba: np.ndarray, width: int) -> np.ndarray:
    """Centre a glyph on a transparent canvas ``width`` pixels wide.

    The burst numerals run from a narrow I to a wide III; on one canvas every
    row label has the same width and the faces stay in one column.
    """
    height, current = rgba.shape[:2]
    if current >= width:
        return rgba
    out = np.zeros((height, width, 4), dtype=rgba.dtype)
    left = (width - current) // 2
    out[:, left:left + current] = rgba
    return out


# As wide as the widest burst glyph the site ships (III and the all-stage mark, 40px).
BURST_CANVAS = 40


class Icons:
    """The icons one chart theme draws, with the units that had to fall back to names."""

    def __init__(self, theme: Theme, directory: Path | None = None) -> None:
        self.theme = theme
        self.directory = directory or icons_dir()
        self.named_units: set[str] = set()

    def face(self, unit_id: str) -> np.ndarray | None:
        """A unit's face; a unit with its treasure gets its base's, with the heart."""
        image = _read(unit_icon_path(str(unit_id), self.directory))
        if image is None:
            self.named_units.add(str(unit_id))
            return None
        face = _round_corners(image, FACE_CORNER)
        return with_heart(face) if treasure_base(str(unit_id)) else face

    def element(self, element: object) -> np.ndarray | None:
        return _read(element_icon_path(element, self.directory)) if isinstance(element, str) and element else None

    def burst(self, burst: object) -> np.ndarray | None:
        if not (isinstance(burst, str) and burst):
            return None
        image = self._glyph(_read(burst_icon_path(burst, self.directory)))
        return None if image is None else _pad_width(image, BURST_CANVAS)

    def _glyph(self, image: np.ndarray | None) -> np.ndarray | None:
        """Burst glyphs are one flat white; draw them in the theme's secondary
        ink so they read on the light surface as well as the dark one."""
        if image is None:
            return None
        tinted = image.copy()
        tinted[..., :3] = to_rgb(self.theme.ink_secondary)
        return tinted


def picture(image: np.ndarray, height_pt: float) -> OffsetImage:
    """An image ``height_pt`` points tall, whatever its pixel size."""
    return OffsetImage(image, zoom=height_pt / image.shape[0], resample=True, interpolation="antialiased")


def line(parts: list, *, height_pt: float, fontsize: float, color: str, weight: str = "normal",
         sep_pt: float = 3.0) -> HPacker:
    """Words and icons on one line, centred vertically.

    ``parts`` holds strings and RGBA arrays; an array is drawn ``height_pt`` tall,
    or at the height given with it as ``(array, height)``.
    """
    children = []
    for part in parts:
        if isinstance(part, tuple):
            children.append(picture(part[0], part[1]))
        elif isinstance(part, np.ndarray):
            children.append(picture(part, height_pt))
        elif part:
            children.append(TextArea(str(part), textprops={"fontsize": fontsize, "color": color,
                                                           "fontweight": weight}))
    return HPacker(children=children, align="center", pad=0, sep=sep_pt)


def place(ax, box, xy, *, xycoords, offset=(0.0, 0.0), align=(0.5, 0.5)) -> AnnotationBbox:
    """Put an offset box on ``ax`` at ``xy``, nudged by ``offset`` points."""
    artist = AnnotationBbox(box, xy, xycoords=xycoords, xybox=offset, boxcoords="offset points",
                            box_alignment=align, frameon=False, pad=0.0, annotation_clip=False)
    ax.add_artist(artist)
    return artist
