"""Command line entry point.

    nikke asof 2024-11-04            what was live then: Solo Raid season, unit pool, banners
    nikke asof 2주년                 the same, for the Nth launch anniversary
    nikke seasons                    every Solo Raid season with its real dates
    nikke tier                       tiers now: last season, the live one, the next one, overall
    nikke tier 2주년                 the same, as the data stood then
    nikke tier --unit 크라운         one unit's tier, season by season
    nikke tier --exclude NA          any of these on another server sample (--server KR,JP)
    nikke raid                       the newest season: units by usage, with the deck split
    nikke raid 40 크라운             one unit in one season (--server, --exclude, --top narrow it)
    nikke check                      does the timeline need a human? (exit 1 if so)

    nikke collect roster             fetch the roster sources
    nikke collect notices            fetch new/edited official notices (site + Naver lounge)
    nikke collect enikk-meta         fetch Solo Raid season metadata and the unit table from enikk
    nikke probe enikk                reconnaissance on the ranking site's API
    nikke collect enikk              fetch Solo Raid rankings (new and changed seasons)
    nikke build timeline             snapshots -> roster, releases, banners, Solo Raid calendar
    nikke build roster               snapshots -> data/processed/roster.csv (names only)
    nikke build raids                snapshots -> raid_entries.csv
    nikke analyze                    processed tables -> metric tables
    nikke viz                        metric tables -> reports/*.png

Rankings pool every server (GLOBAL, JP, KR, NA, SEA, TW-HK) unless
config/tiers.yaml says otherwise. --server keeps only the servers named,
--exclude drops them; both take any case, Korean names (한국, 일본, 북미,
동남아, 대만) and comma-separated lists, and neither changes committed tables.
    nikke refresh                    the whole pipeline, in order
    nikke status                     what exists on disk right now

Every command is a thin wrapper: argument parsing here, logic in the modules.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import paths


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _emit(payload: object) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _servers(args: argparse.Namespace):
    """The server choice on the command line; empty when neither option was given."""
    from .servers import ServerFilter

    return ServerFilter.of(args.server or (), args.exclude or ())


# --------------------------------------------------------------------------
# questions about the past
# --------------------------------------------------------------------------

def cmd_asof(args: argparse.Namespace) -> int:
    from .timeline import Timeline, render

    view = Timeline.load().at(args.moment)
    if args.json:
        _emit(view.to_dict())
    else:
        print(render(view, list_units=args.units))
    return 0


def cmd_tier(args: argparse.Namespace) -> int:
    from .tierlist import TierBook, render, render_unit

    try:
        book = TierBook.load(servers=_servers(args))
    except (LookupError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.unit:
        try:
            history = book.unit(args.unit, args.moment)
        except LookupError as exc:
            print(exc, file=sys.stderr)
            return 1
        if args.json:
            _emit({"unit": history.info, "sample": history.sample.to_dict() if history.sample else None,
                   "profile": history.profile, "seasons": history.rows.to_dict(orient="records")})
        else:
            print(render_unit(history, book.config))
        return 0
    view = book.at(args.moment)
    if args.json:
        _emit(view.to_dict())
    else:
        print(render(view, show_all=args.all))
    return 0


def cmd_raid(args: argparse.Namespace) -> int:
    from .raidstats import RaidBook, render_season, render_unit, unit_record

    try:
        book = RaidBook.load()
        number, unit = book.parse(args.target, args.unit)
        usage = book.season(number, servers=args.server or (), exclude=args.exclude or (), top=args.top)
        row = book.unit(usage, unit) if unit else None
    except LookupError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.json:
        payload = usage.to_dict(include_unused=args.all)
        if row is not None:
            payload.pop("units")
            payload["unit"] = unit_record(row)
        _emit(payload)
    elif row is not None:
        print(render_unit(usage, row))
    else:
        print(render_season(usage, include_unused=args.all))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Does the timeline need a human? Exit status 1 when it does."""
    from datetime import datetime

    from . import health
    from .util.kdate import KST

    now = datetime.now(KST)
    issues = (
        health.read()
        + health.ranking_issues(paths.processed_dir(), now)
        + health.run_issues(paths.processed_dir(), now)
    )
    if args.json:
        _emit([issue.__dict__ for issue in issues])
    else:
        print(health.render(issues))
    return 1 if health.has_errors(issues) else 0


def cmd_seasons(args: argparse.Namespace) -> int:
    from .timeline import Timeline, render_seasons

    timeline = Timeline.load()
    if args.json:
        _emit(
            [
                {
                    "season": s.number,
                    "boss_en": s.boss_en,
                    "boss_ko": s.boss_ko,
                    "element": s.element,
                    "weak_element": s.weak_element,
                    "periods": [
                        {"start": p.start.isoformat(), "end": p.end.isoformat() if p.end else None, "end_reason": p.end_reason}
                        for p in s.periods
                    ],
                    "disrupted": s.disrupted,
                    "record_reset": s.record_reset,
                    "checks": list(s.checks),
                }
                for s in timeline.seasons()
            ]
        )
    else:
        print(render_seasons(timeline))
    return 0


# --------------------------------------------------------------------------
# collect
# --------------------------------------------------------------------------

def cmd_collect_roster(args: argparse.Namespace) -> int:
    from .collect import roster as collector

    results: dict[str, object] = {}
    if args.source in ("all", "gamefiles"):
        results["gamefiles"] = str(collector.collect_gamefiles())
    if args.source in ("all", "nikkeutils"):
        results["nikkeutils"] = str(collector.collect_nikkeutils())
    _emit(results)
    return 0


def cmd_collect_notices(args: argparse.Namespace) -> int:
    from .collect import notices

    results: dict[str, object] = {}
    if args.source in ("all", "official"):
        results["official"] = notices.collect_official(full=args.full).__dict__
    if args.source in ("all", "naver"):
        results["naver"] = notices.collect_naver(full=args.full).__dict__
    _emit(results)
    return 0


def cmd_collect_enikk_meta(args: argparse.Namespace) -> int:
    from .collect import enikk

    _emit(
        {
            "seasons": enikk.collect_seasons(base_url=args.base_url, full=args.full),
            "characters": enikk.collect_characters(base_url=args.base_url),
        }
    )
    return 0


def cmd_probe_enikk(args: argparse.Namespace) -> int:
    from .collect import enikk

    report = enikk.probe(base_url=args.base_url)
    _emit(
        {
            "snapshot_dir": report.snapshot_dir,
            "next_build_id": report.next_build_id,
            "json_endpoints": [f.__dict__ for f in report.json_endpoints],
            "responses": len(report.findings),
        }
    )
    return 0


def cmd_collect_enikk(args: argparse.Namespace) -> int:
    from .collect import enikk
    from .config import load_enikk_config

    config = load_enikk_config(Path(args.config) if args.config else None)
    _emit(enikk.collect_rankings(config=config, seasons=args.seasons, full=args.full))
    return 0


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def cmd_build_timeline(args: argparse.Namespace) -> int:
    from .build import pipeline

    _emit(pipeline.build_timeline())
    return 0


def cmd_build_roster(args: argparse.Namespace) -> int:
    from .build import enikk_meta, roster

    _emit(roster.build(enikk=enikk_meta.load_characters()))
    return 0


def cmd_build_raids(args: argparse.Namespace) -> int:
    from .build import raids
    from .config import load_enikk_config

    config = load_enikk_config(Path(args.config) if args.config else None)
    _emit(raids.build(mapping=config.mapping))
    return 0


# --------------------------------------------------------------------------
# refresh: the whole pipeline
# --------------------------------------------------------------------------

def _attempt(steps: dict[str, object], failures: dict[str, str], name: str, action) -> None:
    """Run one network step; a source being down must not stop the others.

    The failure is still recorded: the run carries on with the snapshots it
    has, and then ends with a non-zero status so nobody mistakes it for fresh.
    """
    try:
        result = action()
        steps[name] = result.__dict__ if hasattr(result, "__dict__") else result
    except Exception as exc:  # network policy, outage, a changed API
        logging.getLogger(__name__).warning("%s failed: %s", name, exc)
        steps[name] = {"failed": str(exc)}
        failures[name] = str(exc)


def cmd_refresh(args: argparse.Namespace) -> int:
    """Collect everything new, then rebuild every table in dependency order.

    This is the command a scheduled job runs. Nothing in it needs a human, and
    nothing in it needs a model: a new patch, a new unit, a new Solo Raid
    season or a suspended one are all picked up by re-running it. It exits with
    status 1 when a source could not be collected or the result needs a look
    (see ``nikke check``), so an unattended run never fails quietly.
    """
    from datetime import datetime

    from . import health
    from .build import pipeline
    from .collect import enikk, notices
    from .collect import roster as roster_collector
    from .config import load_enikk_config
    from .util.kdate import KST

    steps: dict[str, object] = {}
    failures: dict[str, str] = {}

    if not args.offline:
        _attempt(steps, failures, "collect.roster.gamefiles", lambda: str(roster_collector.collect_gamefiles()))
        _attempt(steps, failures, "collect.roster.nikkeutils", lambda: str(roster_collector.collect_nikkeutils()))
        _attempt(steps, failures, "collect.notices.official", lambda: notices.collect_official())
        _attempt(steps, failures, "collect.notices.naver", lambda: notices.collect_naver())
        _attempt(steps, failures, "collect.enikk.seasons", lambda: enikk.collect_seasons())
        _attempt(steps, failures, "collect.enikk.characters", lambda: enikk.collect_characters())
        _attempt(
            steps,
            failures,
            "collect.enikk.rankings",
            lambda: enikk.collect_rankings(config=load_enikk_config(), seasons=args.seasons),
        )

    steps["build.timeline"] = pipeline.build_timeline()

    from .build import raids

    try:
        steps["build.raids"] = raids.build(mapping=load_enikk_config().mapping)
    except RuntimeError as exc:
        steps["build.raids"] = {"skipped": str(exc)}

    from .analyze import pipeline as analysis

    try:
        steps["analyze"] = analysis.run(content=args.content)
    except RuntimeError as exc:
        steps["analyze"] = {"skipped": str(exc)}
    except LookupError as exc:  # config/tiers.yaml names a server the rankings do not have
        steps["analyze"] = {"failed": str(exc)}
        failures["analyze"] = f"config/tiers.yaml 의 서버 설정: {exc}"
    else:
        from .viz import charts

        steps["viz"] = charts.render_all()

    now = datetime.now(KST)
    issues = (
        health.read()
        + health.ranking_issues(paths.processed_dir(), now)
        + health.run_issues(paths.processed_dir(), now, failures)
    )
    steps["health"] = [issue.__dict__ for issue in issues if issue.level != "info"]
    _emit(steps)
    print(health.render(issues), file=sys.stderr)
    return 1 if health.has_errors(issues) else 0


# --------------------------------------------------------------------------
# analyze / viz / status
# --------------------------------------------------------------------------

def cmd_analyze(args: argparse.Namespace) -> int:
    """The committed metric tables; with --server/--exclude, the same tables on
    that sample under data/interim/servers/ (not committed)."""
    from .analyze import pipeline

    chosen = _servers(args)
    try:
        if chosen:
            _emit(pipeline.run_servers(chosen, content=args.content, reuse=False))
        else:
            _emit(pipeline.run(content=args.content))
    except LookupError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


def cmd_viz(args: argparse.Namespace) -> int:
    """Charts of the committed tables into reports/; with --server/--exclude,
    charts of that sample into reports/servers/<choice>/."""
    from .viz import charts

    units = [u.strip() for u in args.units.split(",") if u.strip()] if args.units else None
    chosen = _servers(args)
    if not chosen:
        _emit(charts.render_all(top_n=args.top, units=units))
        return 0
    from .analyze import pipeline

    try:
        tables = pipeline.run_servers(chosen)
    except (LookupError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    _emit(charts.render_all(data_dir=Path(tables["out_dir"]), out_dir=paths.reports_dir() / "servers" / chosen.slug,
                            top_n=args.top, units=units, sample=chosen.english))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from .util.snapshot import list_runs

    sources = [
        "roster_gamefiles",
        "roster_nikkeutils",
        "notices_official",
        "notices_naver",
        "enikk_seasons",
        "enikk_characters",
        "enikk_probe",
        "enikk_soloraid",
    ]
    snapshots = {
        source: [
            {"run_id": run.run_id, "entries": run.manifest.get("entry_count", 0)}
            for run in list_runs(source)
        ]
        for source in sources
    }
    processed = sorted(p.name for p in paths.processed_dir().glob("*.csv"))
    _emit({"data_root": str(paths.data_root()), "snapshots": snapshots, "processed": processed})
    return 0


# --------------------------------------------------------------------------

def _server_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--server", action="append", default=None, metavar="NAME",
                   help="only these servers (GLOBAL, JP, KR, NA, SEA, TW-HK, or 한국, 일본 ...); "
                        "repeat or comma-separate")
    p.add_argument("--exclude", action="append", default=None, metavar="NAME",
                   help="every server but these; repeat or comma-separate")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nikke",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("asof", help="what was live at a moment (KST)")
    p.add_argument("moment", help="2024-11-04, 2024-11-04T15:00, or 2주년")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--units", action="store_true", help="list every unit in the pool")
    p.set_defaults(func=cmd_asof)

    p = sub.add_parser("tier", help="tiers at a moment (default: now), or one unit's history")
    p.add_argument("moment", nargs="?", default=None, help="2024-11-04, 2024-11-04T15:00 or 2주년 (default: now)")
    p.add_argument("--unit", default=None, help="one unit's season-by-season record, by Korean or English name")
    p.add_argument("--all", action="store_true", help="also list C and D")
    _server_options(p)
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_tier)

    p = sub.add_parser("raid", help="one Solo Raid season's usage: units by rankers, with the deck split")
    p.add_argument("target", nargs="?", default=None,
                   help="season number, a moment (2024-11-04, 2주년), or a unit name (default: newest season)")
    p.add_argument("unit", nargs="?", default=None, help="one unit, by Korean or English name or id")
    _server_options(p)
    p.add_argument("--top", type=int, default=None, help="only ranks 1..N of each server")
    p.add_argument("--all", action="store_true", help="also list the units available then that nobody fielded")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_raid)

    p = sub.add_parser("check", help="does the timeline need a human? (exit 1 if so)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("seasons", help="every Solo Raid season with its real dates")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_seasons)

    collect = sub.add_parser("collect", help="fetch raw snapshots").add_subparsers(
        dest="target", required=True
    )

    p = collect.add_parser("roster", help="roster sources (game files + nikke-utils)")
    p.add_argument("--source", choices=["all", "gamefiles", "nikkeutils"], default="all")
    p.set_defaults(func=cmd_collect_roster)

    p = collect.add_parser("notices", help="official notices: nikke-kr.com and the Naver lounge")
    p.add_argument("--source", choices=["all", "official", "naver"], default="all")
    p.add_argument("--full", action="store_true", help="re-read every notice, not just new or recent ones")
    p.set_defaults(func=cmd_collect_notices)

    p = collect.add_parser("enikk-meta", help="Solo Raid season metadata and the unit table from enikk")
    p.add_argument("--base-url", default="https://enikk.app")
    p.add_argument("--full", action="store_true", help="re-read every season")
    p.set_defaults(func=cmd_collect_enikk_meta)

    p = collect.add_parser("enikk", help="Solo Raid rankings (new and changed seasons)")
    p.add_argument("--config", default=None)
    p.add_argument("--seasons", nargs="*", type=int, default=None, help="re-read these seasons regardless")
    p.add_argument("--full", action="store_true", help="re-read every season")
    p.set_defaults(func=cmd_collect_enikk)

    probe = sub.add_parser("probe", help="reconnaissance").add_subparsers(
        dest="target", required=True
    )
    p = probe.add_parser("enikk", help="discover the ranking site's data endpoints")
    p.add_argument("--base-url", default="https://enikk.app")
    p.set_defaults(func=cmd_probe_enikk)

    build = sub.add_parser("build", help="snapshots -> processed tables").add_subparsers(
        dest="target", required=True
    )

    p = build.add_parser("timeline", help="roster, releases, banners and the Solo Raid calendar")
    p.set_defaults(func=cmd_build_timeline)

    p = build.add_parser("roster", help="roster and alias table only (no notice-based dates)")
    p.set_defaults(func=cmd_build_roster)

    p = build.add_parser("raids", help="ranking snapshots -> raid_entries.csv (one row per unit slot)")
    p.add_argument("--config", default=None)
    p.set_defaults(func=cmd_build_raids)

    p = sub.add_parser("analyze", help="compute metric tables")
    p.add_argument("--content", default="soloraid")
    _server_options(p)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("viz", help="render charts")
    p.add_argument("--top", type=int, default=6, help="units in the trajectory chart (strongest overall)")
    p.add_argument("--units", default=None, help="comma-separated unit names for the trajectory chart instead")
    _server_options(p)
    p.set_defaults(func=cmd_viz)

    p = sub.add_parser("refresh", help="run the whole pipeline in dependency order")
    p.add_argument("--offline", action="store_true", help="skip every network step")
    p.add_argument("--seasons", nargs="*", type=int, default=None, help="re-read these seasons' rankings regardless")
    p.add_argument("--content", default="soloraid")
    p.set_defaults(func=cmd_refresh)

    p = sub.add_parser("status", help="show what is on disk")
    p.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    paths.ensure_dirs()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
