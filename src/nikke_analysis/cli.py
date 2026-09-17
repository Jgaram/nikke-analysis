"""Command line entry point.

    nikke collect roster            fetch the roster sources
    nikke collect patchnotes        fetch update announcements
    nikke probe enikk               reconnaissance on the ranking site's API
    nikke collect enikk             fetch Solo Raid rankings (needs config)
    nikke build roster              snapshots -> data/processed/roster.csv
    nikke build patches             snapshots -> patches.csv / unit_releases.csv
    nikke build raids               snapshots -> raid_entries.csv
    nikke analyze                   processed tables -> metric tables
    nikke viz                       metric tables -> reports/*.png
    nikke refresh                   the whole pipeline, in order
    nikke status                    what exists on disk right now

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


def cmd_collect_patchnotes(args: argparse.Namespace) -> int:
    from .collect import patchnotes as collector

    results: dict[str, object] = {}
    if args.source in ("all", "steam"):
        result = collector.collect_steam(appid=args.steam_appid, max_pages=args.max_pages)
        results["steam"] = result.__dict__
    if args.source in ("all", "official"):
        if not args.index_url:
            raise SystemExit("--index-url is required for the official news collector")
        results["official"] = collector.collect_official(
            index_url=args.index_url, max_pages=args.max_pages
        )
    _emit(results)
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

def cmd_build_roster(args: argparse.Namespace) -> int:
    from .build import roster

    patch_releases = None
    if not args.ignore_patches:
        from .build import patches

        patch_releases = patches.load_unit_releases()
    _emit(roster.build(patch_releases=patch_releases))
    return 0


def cmd_build_patches(args: argparse.Namespace) -> int:
    from .build import patches

    _emit(patches.build())
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

def cmd_refresh(args: argparse.Namespace) -> int:
    """Collect, build, analyse and render - in the order the stages depend on.

    The roster is built twice on purpose. Release dates come from patch notes,
    but finding a unit in a patch note needs the alias table that the roster
    build produces. So: roster (names only) -> patches (dates) -> roster again
    (dates applied). Two cheap passes beat a circular dependency.

    This is the command a scheduled job runs. Nothing in it needs a human, and
    nothing in it needs a model: a new patch and a new season are picked up by
    re-running it.
    """
    from .build import patches, roster
    from .collect import patchnotes
    from .collect import roster as roster_collector
    from .config import load_enikk_config

    steps: dict[str, object] = {}

    if not args.offline:
        steps["collect.roster"] = {
            "gamefiles": str(roster_collector.collect_gamefiles()),
            "nikkeutils": str(roster_collector.collect_nikkeutils()),
        }
        if not args.skip_patchnotes:
            try:
                steps["collect.patchnotes"] = patchnotes.collect_steam(
                    appid=args.steam_appid
                ).__dict__
            except Exception as exc:  # network policy, app-id ambiguity, outage
                steps["collect.patchnotes"] = {"skipped": str(exc)}

        config = load_enikk_config()
        if config.ready and (args.seasons or config.seasons):
            from .collect import enikk

            steps["collect.enikk"] = enikk.collect(
                base_url=config.base_url,
                endpoint_template=config.endpoint_template,
                seasons=args.seasons or config.seasons,
                bosses=config.bosses or ("",),
                extra_params=config.extra_params,
            )
        else:
            steps["collect.enikk"] = {"skipped": "config/enikk.yaml is not configured yet"}

    # Pass 1: names only, so patch notes have an alias table to match against.
    steps["build.roster(pass 1)"] = roster.build()
    try:
        steps["build.patches"] = patches.build()
    except RuntimeError as exc:
        steps["build.patches"] = {"skipped": str(exc)}
    # Pass 2: now with patch-note release dates.
    steps["build.roster(pass 2)"] = roster.build(patch_releases=patches.load_unit_releases())

    from .build import raids
    from .config import load_enikk_config as _load

    try:
        steps["build.raids"] = raids.build(mapping=_load().mapping)
    except RuntimeError as exc:
        steps["build.raids"] = {"skipped": str(exc)}

    from .analyze import pipeline

    try:
        steps["analyze"] = pipeline.run(content=args.content)
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
        "patchnotes_steam",
        "patchnotes_official",
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

    collect = sub.add_parser("collect", help="fetch raw snapshots").add_subparsers(
        dest="target", required=True
    )

    p = collect.add_parser("roster", help="roster sources (game files + nikke-utils)")
    p.add_argument("--source", choices=["all", "gamefiles", "nikkeutils"], default="all")
    p.set_defaults(func=cmd_collect_roster)

    p = collect.add_parser("patchnotes", help="update announcements")
    p.add_argument("--source", choices=["all", "steam", "official"], default="steam")
    p.add_argument("--steam-appid", type=int, default=None, help="skip app-id resolution")
    p.add_argument("--index-url", default=None, help="news index URL for --source official")
    p.add_argument("--max-pages", type=int, default=40)
    p.set_defaults(func=cmd_collect_patchnotes)

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

    p = build.add_parser("roster")
    p.add_argument(
        "--ignore-patches",
        action="store_true",
        help="do not use patch-note release dates (useful for isolating sources)",
    )
    p.set_defaults(func=cmd_build_roster)

    p = build.add_parser("patches")
    p.set_defaults(func=cmd_build_patches)

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
    p.add_argument("--skip-patchnotes", action="store_true")
    p.add_argument("--steam-appid", type=int, default=None)
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
