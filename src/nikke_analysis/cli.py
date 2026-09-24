"""Command line entry point.

    nikke asof 2024-11-04            what was live then: Solo Raid season, unit pool, banners
    nikke asof 2주년                 the same, for the Nth launch anniversary
    nikke seasons                    every Solo Raid season with its real dates

    nikke collect roster             fetch the roster sources
    nikke collect notices            fetch new/edited official notices (site + Naver lounge)
    nikke collect enikk-meta         fetch Solo Raid season metadata and the unit table from enikk
    nikke probe enikk                reconnaissance on the ranking site's API
    nikke collect enikk              fetch Solo Raid rankings (needs config)
    nikke build timeline             snapshots -> roster, releases, banners, Solo Raid calendar
    nikke build roster               snapshots -> data/processed/roster.csv (names only)
    nikke build raids                snapshots -> raid_entries.csv
    nikke analyze                    processed tables -> metric tables
    nikke viz                        metric tables -> reports/*.png
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
    seasons = args.seasons or config.seasons
    if not seasons:
        raise SystemExit("no seasons given; pass --seasons or set them in config/enikk.yaml")
    snapshot = enikk.collect(
        base_url=config.base_url,
        endpoint_template=config.endpoint_template,
        seasons=seasons,
        bosses=config.bosses or ("",),
        extra_params=config.extra_params,
    )
    _emit({"snapshot_dir": snapshot, "seasons": list(seasons)})
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

def _attempt(steps: dict[str, object], name: str, action) -> None:
    """Run one network step; a source being down must not stop the others."""
    try:
        result = action()
        steps[name] = result.__dict__ if hasattr(result, "__dict__") else result
    except Exception as exc:  # network policy, outage, a changed API
        logging.getLogger(__name__).warning("%s failed: %s", name, exc)
        steps[name] = {"failed": str(exc)}


def cmd_refresh(args: argparse.Namespace) -> int:
    """Collect everything new, then rebuild every table in dependency order.

    This is the command a scheduled job runs. Nothing in it needs a human, and
    nothing in it needs a model: a new patch, a new unit, a new Solo Raid
    season or a suspended one are all picked up by re-running it.
    """
    from .build import pipeline
    from .collect import enikk, notices
    from .collect import roster as roster_collector
    from .config import load_enikk_config

    steps: dict[str, object] = {}

    if not args.offline:
        _attempt(steps, "collect.roster.gamefiles", lambda: str(roster_collector.collect_gamefiles()))
        _attempt(steps, "collect.roster.nikkeutils", lambda: str(roster_collector.collect_nikkeutils()))
        _attempt(steps, "collect.notices.official", lambda: notices.collect_official())
        _attempt(steps, "collect.notices.naver", lambda: notices.collect_naver())
        _attempt(steps, "collect.enikk.seasons", lambda: enikk.collect_seasons())
        _attempt(steps, "collect.enikk.characters", lambda: enikk.collect_characters())

        config = load_enikk_config()
        if config.ready and (args.seasons or config.seasons):
            _attempt(
                steps,
                "collect.enikk.rankings",
                lambda: enikk.collect(
                    base_url=config.base_url,
                    endpoint_template=config.endpoint_template,
                    seasons=args.seasons or config.seasons,
                    bosses=config.bosses or ("",),
                    extra_params=config.extra_params,
                ),
            )
        else:
            steps["collect.enikk.rankings"] = {"skipped": "config/enikk.yaml is not configured yet"}

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
        _emit(steps)
        return 0

    from .viz import charts

    steps["viz"] = charts.render_all()
    _emit(steps)
    return 0


# --------------------------------------------------------------------------
# analyze / viz / status
# --------------------------------------------------------------------------

def cmd_analyze(args: argparse.Namespace) -> int:
    from .analyze import pipeline

    _emit(pipeline.run(content=args.content))
    return 0


def cmd_viz(args: argparse.Namespace) -> int:
    from .viz import charts

    _emit(charts.render_all(top_n=args.top))
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

    p = collect.add_parser("enikk", help="Solo Raid rankings")
    p.add_argument("--config", default=None)
    p.add_argument("--seasons", nargs="*", default=None)
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

    p = build.add_parser("raids")
    p.add_argument("--config", default=None)
    p.set_defaults(func=cmd_build_raids)

    p = sub.add_parser("analyze", help="compute metric tables")
    p.add_argument("--content", default="soloraid")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("viz", help="render charts")
    p.add_argument("--top", type=int, default=20)
    p.set_defaults(func=cmd_viz)

    p = sub.add_parser("refresh", help="run the whole pipeline in dependency order")
    p.add_argument("--offline", action="store_true", help="skip every network step")
    p.add_argument("--seasons", nargs="*", default=None)
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
