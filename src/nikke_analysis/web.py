"""The tier site: a static page that computes the tiers in the browser.

    nikke web                    build the site into _site/
    nikke web --serve            ... and serve it on http://localhost:8000

The page itself lives in ``web/`` (plain HTML, CSS and JavaScript, no build
step). This module gives it its data and puts the two together:

``data/model.json``  every unit (names, elements, burst, release and treasure
                     instants), every Solo Raid season a notice has scheduled or
                     that has rankings (boss, weak element, real dates, when its
                     rankings were collected) and the defaults of
                     config/tiers.yaml
``data/decks.json``  every ranked player's fought decks, season by season: the
                     server, the rank, and each deck's damage and units
``icons/``           the unit faces, boss pictures and attribute icons of
                     data/assets/icons/

The decks are what the metric tables are computed from, so the page repeats the
whole computation (``web/js/model.js`` follows ``analyze/metrics.py`` and
``analyze/tiers.py``): every parameter of config/tiers.yaml - the servers, the
ranks, the rank weighting, the cuts, the recency, how the overall tier is
formed - is a control on the page, and changing one recomputes the tiers on
the spot. With the defaults the page shows what the committed tables say.

The decks come from ``raid_entries.csv`` (``nikke build raids``, offline). The
build is deterministic: the same tables give the same files, and the page's own
files are stamped with a hash of their content so a browser never mixes a new
page with an old cached script.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from .analyze import metrics, tiers
from .paths import REPO_ROOT, boss_icon_path, icons_dir, processed_dir
from .servers import SERVER_KO, ordered

log = logging.getLogger(__name__)

WEB_DIR = REPO_ROOT / "web"
SITE_DIR = REPO_ROOT / "_site"
ICON_KINDS = ("units", "bosses", "elements", "bursts", "classes", "weapons", "manufacturers")
LAUNCH = "2022-11-04T00:00:00+09:00"
# Files whose references to the page's own scripts and styles get the content stamp.
STAMPED = (".html", ".js", ".css")
_LOCAL_REF = re.compile(r"""((?:from\s+|import\s*\(\s*|import\s+|href=|src=)["'])(\.{0,2}/?[\w./-]+\.(?:js|css))(["'])""")


def _read(path: Path, **kwargs: Any) -> pd.DataFrame:
    if not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False, **kwargs)


def _ms(value: Any) -> int | None:
    """An instant as epoch milliseconds (UTC), None when missing."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        return None
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    return int(stamp.value // 1_000_000)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _units(roster: pd.DataFrame) -> list[dict[str, Any]]:
    released = metrics.release_instants(roster)
    treasure = metrics.treasure_instants(roster)
    units = []
    for _, row in roster.drop_duplicates("unit_id").iterrows():
        unit_id = row["unit_id"]
        release = released.get(unit_id)
        units.append({
            "id": unit_id,
            "ko": _text(row.get("name_ko")),
            "en": _text(row.get("name_en")),
            "element": _text(row.get("element")),
            "extra": metrics.listed_elements(row.get("extra_elements")),
            "treasureElements": metrics.listed_elements(row.get("treasure_elements")),
            "burst": _text(row.get("burst")),
            "class": _text(row.get("unit_class")),
            "rarity": _text(row.get("rarity")),
            "weapon": _text(row.get("weapon")),
            "manufacturer": _text(row.get("manufacturer")),
            "squad": _text(row.get("squad")),
            "release": _ms(release) if release is not None else None,
            "releaseDate": _text(row.get("release_date")),
            "releaseSource": _text(row.get("release_date_source")),
            "treasure": _ms(treasure.get(unit_id)) if unit_id in treasure.index else None,
        })
    return sorted(units, key=lambda u: u["id"])


def _seasons(seasons: pd.DataFrame, periods: pd.DataFrame, entries: pd.DataFrame,
             icons: Path | None = None) -> list[dict[str, Any]]:
    collected = pd.to_datetime(entries.groupby("season")["collected_at"].max(), errors="coerce", utc=True)
    servers = entries.groupby("season")["server"].agg(lambda s: ordered(s.unique()))
    spans: dict[int, list[list[Any]]] = {}
    for _, row in periods.iterrows():
        spans.setdefault(int(row["season"]), []).append(
            [_ms(row["start_at"]), _ms(row["end_at"]), _text(row.get("end_reason"))])
    out = []
    for _, row in seasons.iterrows():
        number = int(row["season"])
        # A season only enikk knows about (no notice yet, no rankings) is not public; the site doesn't show it.
        if number not in spans and number not in collected.index:
            continue
        out.append({
            "season": number,
            "bossEn": _text(row.get("boss_en")),
            "bossKo": _text(row.get("boss_ko")),
            # the picture's file name under icons/bosses/, when there is one on disk
            "bossImage": image if (image := _text(row.get("boss_image"))) and boss_icon_path(image, icons).is_file()
            else "",
            "bossElement": _text(row.get("element")),
            "weak": _text(row.get("weak_element")),
            "start": _ms(row.get("start_at")),
            "end": _ms(row.get("end_at")),
            "scheduledStart": _ms(row.get("scheduled_start")),
            "scheduledEnd": _ms(row.get("scheduled_end")),
            "periods": spans.get(number, []),
            "disrupted": _text(row.get("disrupted")) == "1",
            "collected": _ms(collected.get(number)) if number in collected.index else None,
            "servers": list(servers.get(number, [])),
        })
    return sorted(out, key=lambda s: s["season"])


def _decks(entries: pd.DataFrame, units: list[dict[str, Any]], servers: list[str]) -> dict[str, Any]:
    """Every ranked player's fought decks, per season, in the table's order:
    ``[server, rank, [damage, unit, ...], ...]`` with the server and the units as
    indexes into ``servers`` and ``units``. Decks that dealt no damage were not
    fought and never count, so they are left out."""
    index = {u["id"]: i for i, u in enumerate(units)}
    at = {s: i for i, s in enumerate(servers)}
    fought = entries[(entries["deck_score"] > 0) & (entries["rank"] >= 1)]
    seasons: dict[str, list[list[Any]]] = {}
    for (season, server, _player), rows in fought.groupby(["season", "server", "player"], sort=False):
        ranker: list[Any] = [at[server], int(rows["rank"].iloc[0])]
        for _deck, deck in rows.sort_values(["deck", "slot"]).groupby("deck", sort=True):
            ranker.append([int(deck["deck_score"].iloc[0])] + [index[u] for u in deck["unit_id"]])
        seasons.setdefault(str(int(season)), []).append(ranker)
    return {"seasons": seasons}


def _defaults(config: tiers.TierConfig) -> dict[str, Any]:
    return {
        "topN": config.top_n,
        "servers": list(config.servers),
        "excludeServers": list(config.exclude_servers),
        "rankWeighting": config.rank_weighting,
        "cuts": [[label, value] for label, value in config.cuts],
        "overallCuts": [[label, value] for label, value in config.overall_cuts],
        "halfLifeDays": config.half_life_days,
        "priorStrength": config.prior_strength,
        "overall": config.overall,
        "minElementsObserved": config.min_elements_observed,
        "includeLive": config.include_live,
        "minTier": config.min_tier,
        "retireAfterDays": config.retire_after_days,
        "retireAfterOwnSeasons": config.retire_after_own_seasons,
        "generalityBands": list(config.generality_bands),
        "curveMinTier": config.curve_min_tier,
        "curveWide": config.curve_wide,
        "metaWindowDays": config.meta_window_days,
    }


def export(data_dir: Path | None = None, config: tiers.TierConfig | None = None,
           icons: Path | None = None) -> tuple[dict, dict]:
    """The page's two data files, ``model.json`` and ``decks.json``, as dicts."""
    directory = data_dir or processed_dir()
    config = config or tiers.load_tier_config()
    roster = _read(directory / "roster.csv")
    seasons = _read(directory / "soloraid_seasons.csv")
    periods = _read(directory / "soloraid_periods.csv")
    entries = _read(directory / "raid_entries.csv")
    if roster.empty or seasons.empty:
        raise RuntimeError("roster.csv or soloraid_seasons.csv is missing; run `nikke build timeline` first")
    if entries.empty:
        raise RuntimeError("raid_entries.csv is missing; run `nikke build raids` first (offline, a few seconds)")
    if "content" in entries.columns:
        entries = entries[entries["content"] == "soloraid"]
    entries = entries.assign(
        season=pd.to_numeric(entries["season"], errors="coerce"),
        rank=pd.to_numeric(entries["rank"], errors="coerce").fillna(0).astype(int),
        deck=pd.to_numeric(entries["deck"], errors="coerce").fillna(0).astype(int),
        slot=pd.to_numeric(entries["slot"], errors="coerce").fillna(0).astype(int),
        deck_score=pd.to_numeric(entries["deck_score"], errors="coerce").fillna(0),
    ).dropna(subset=["season"])
    entries["season"] = entries["season"].astype(int)

    units = _units(roster)
    known = {u["id"] for u in units}
    missing = sorted(set(entries["unit_id"]) - known)
    if missing:  # every ranked name resolves to a roster id; this only guards the index
        raise RuntimeError(f"raid_entries.csv has units the roster does not: {', '.join(missing)}")
    servers = ordered(entries["server"].unique())
    season_list = _seasons(seasons, periods, entries, icons)
    decks = _decks(entries, units, servers)
    newest = max((s["collected"] for s in season_list if s["collected"] is not None), default=None)
    model = {
        "asOf": newest + 86_400_000 - 1_000 if newest is not None else None,
        "launch": _ms(LAUNCH),
        "elements": list(metrics.ELEMENTS),
        "servers": servers,
        "serverNames": {s: SERVER_KO.get(s, s) for s in servers},
        "defaults": _defaults(config),
        "units": units,
        "seasons": season_list,
    }
    return model, decks


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _stamp_references(text: str, stamp: str) -> str:
    """``./app.js`` -> ``./app.js?v=<stamp>`` for every local script and stylesheet reference."""
    return _LOCAL_REF.sub(lambda m: f"{m.group(1)}{m.group(2)}?v={stamp}{m.group(3)}", text)


def build(
    out_dir: Path | None = None,
    *,
    data_dir: Path | None = None,
    web_dir: Path | None = None,
    icons: Path | None = None,
    config: tiers.TierConfig | None = None,
) -> dict[str, Any]:
    """The whole site in ``out_dir`` (default ``_site/``), replacing what was there."""
    target = out_dir or SITE_DIR
    source = web_dir or WEB_DIR
    if not (source / "index.html").is_file():
        raise RuntimeError(f"no page to build: {source / 'index.html'} is missing")
    model, decks = export(data_dir, config, icons)
    model_text, decks_text = _dump(model), _dump(decks)
    data_stamp = hashlib.sha256((model_text + decks_text).encode("utf-8")).hexdigest()[:12]
    model["dataVersion"] = data_stamp
    model_text = _dump(model)

    code = hashlib.sha256()
    files = sorted(p for p in source.rglob("*") if p.is_file())
    for path in files:
        code.update(path.relative_to(source).as_posix().encode("utf-8"))
        code.update(path.read_bytes())
    stamp = code.hexdigest()[:12]

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for path in files:
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix in STAMPED:
            destination.write_text(_stamp_references(path.read_text(encoding="utf-8"), stamp), encoding="utf-8")
        else:
            shutil.copyfile(path, destination)
    (target / "data").mkdir(exist_ok=True)
    (target / "data" / "model.json").write_text(model_text, encoding="utf-8")
    (target / "data" / "decks.json").write_text(decks_text, encoding="utf-8")
    (target / ".nojekyll").write_text("", encoding="utf-8")

    icon_root = icons or icons_dir()
    copied = 0
    for kind in ICON_KINDS:
        folder = icon_root / kind
        if not folder.is_dir():
            continue
        (target / "icons" / kind).mkdir(parents=True, exist_ok=True)
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix in (".png", ".webp"):
                shutil.copyfile(path, target / "icons" / kind / path.name)
                copied += 1
    faces = {p.stem for p in (target / "icons" / "units").glob("*.webp")} if (target / "icons" / "units").is_dir() else set()
    rankers = sum(len(v) for v in decks["seasons"].values())
    summary = {
        "out_dir": str(target),
        "units": len(model["units"]),
        "units_without_face": sorted(u["id"] for u in model["units"] if u["id"] not in faces),
        "seasons": len(model["seasons"]),
        "ranked_seasons": len(decks["seasons"]),
        "rankers": rankers,
        "icons": copied,
        "data_version": data_stamp,
        "code_version": stamp,
        "bytes": {"model.json": len(model_text.encode("utf-8")), "decks.json": len(decks_text.encode("utf-8"))},
    }
    log.info("site built in %s: %s seasons, %s rankers", target, summary["ranked_seasons"], rankers)
    return summary


def serve(directory: Path | None = None, port: int = 8000) -> None:
    """Serve the built site on http://localhost:``port`` until interrupted."""
    import functools
    import http.server

    root = directory or SITE_DIR
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print(f"http://localhost:{port}/  (Ctrl+C 로 종료)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
