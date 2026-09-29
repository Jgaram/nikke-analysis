"""The tier site: the files `nikke web` builds, and the page's own computation
(web/js/model.js, run under Node) against the pipeline's tables.

The page recomputes the tiers from the ranking decks in the browser, so every
parameter of config/tiers.yaml can be a control on it. That only works if it
computes what the pipeline does: with the same parameters, the same lift, usage
and deck split per season, the same element and overall tier at every season's
end, and the same comparison tables. The synthetic world here has a unit whose
skill adds an element and one whose treasure comes mid-run and adds another.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nikke_analysis import web
from nikke_analysis.analyze import pipeline, tiers
from nikke_analysis.servers import ordered
from tests.synthetic import make_world, write_processed

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
DUMP = REPO / "tests" / "web_dump.mjs"

CONFIGS = {
    "defaults": {},
    "servers-top-uniform": {"exclude_servers": ("S2",), "top_n": 8, "rank_weighting": "uniform"},
    "flat-frequency-prior": {"half_life_days": 0.0, "overall": "frequency", "prior_strength": 2.0,
                             "min_elements_observed": 2, "min_tier": "B", "retire_after_days": 40.0,
                             "retire_after_own_seasons": 0, "left_after": 1,
                             "generality_bands": (0.4, 1.2)},
    "max-finished-only-cuts": {"overall": "max", "include_live": False, "half_life_days": 60.0,
                               "cuts": [("SS", 1.6), ("S", 1.2), ("A", 0.9), ("B", 0.6), ("C", 0.3), ("D", 0.0)],
                               "overall_cuts": [("SS", 1.0), ("S", 0.7), ("A", 0.4), ("B", 0.2), ("C", 0.1),
                                                ("D", 0.0)],
                               "retire_after_days": 0.0, "retire_after_own_seasons": 2},
}


@pytest.fixture(scope="module")
def world_dir(tmp_path_factory):
    directory = tmp_path_factory.mktemp("web-processed")
    world = make_world(seasons=9, servers=3, rankers=12, fillers=20, seed=5)
    roster = world.roster.copy()
    roster["extra_elements"] = ""
    roster["treasure_elements"] = ""
    roster["treasure_at"] = ""
    fire = world.element_dps["Fire"]
    roster.loc[roster["unit_id"] == world.universal[0], "extra_elements"] = "Water"
    # The Fire dealer's treasure lands between seasons 4 and 5 and gives it Iron's weakness advantage too.
    seasons = world.seasons.set_index("season")
    treasure = pd.Timestamp(seasons.loc[5, "start_at"]) - pd.Timedelta(days=2)
    roster.loc[roster["unit_id"] == fire, ["treasure_at", "treasure_elements"]] = [treasure.isoformat(), "Iron"]
    world = replace(world, roster=roster)
    write_processed(world, directory)
    return directory, world


@pytest.fixture(scope="module")
def site(world_dir, tmp_path_factory):
    directory, _ = world_dir
    out = tmp_path_factory.mktemp("site")
    summary = web.build(out, data_dir=directory, config=tiers.TierConfig())
    return out, summary


def test_build_writes_the_page_its_data_and_icons(site, world_dir):
    out, summary = site
    _, world = world_dir
    assert (out / "index.html").is_file() and (out / ".nojekyll").is_file()
    model = json.loads((out / "data" / "model.json").read_text(encoding="utf-8"))
    decks = json.loads((out / "data" / "decks.json").read_text(encoding="utf-8"))
    assert len(model["units"]) == len(world.roster)
    assert [s["season"] for s in model["seasons"]] == list(range(1, 10))  # nine ranked; the one only enikk knows is left out
    assert model["servers"] == ["S1", "S2", "S3"] and model["dataVersion"] == summary["data_version"]
    rankers = world.entries.drop_duplicates(["season", "server", "player"])
    assert sum(len(v) for v in decks["seasons"].values()) == len(rankers)
    # every ranker: server, rank, then five decks of damage and five units
    ranker = decks["seasons"]["1"][0]
    assert len(ranker) == 2 + 5 and all(len(deck) == 6 and deck[0] > 0 for deck in ranker[2:])
    fire = next(u for u in model["units"] if u["id"] == world.element_dps["Fire"])
    assert fire["treasure"] is not None and fire["treasureElements"] == ["Iron"]


def test_a_season_shows_once_a_notice_schedules_it(world_dir, tmp_path):
    directory, world = world_dir
    model, _ = web.export(directory, tiers.TierConfig())
    assert "Next Boss" not in json.dumps(model)  # enikk knows it, no notice yet: not on the site
    announced = tmp_path / "processed"
    shutil.copytree(directory, announced)
    start = pd.Timestamp(world.seasons["end_at"].iloc[-2]) + pd.Timedelta(days=28)
    periods = pd.concat([world.periods, pd.DataFrame([{
        "season": 10, "period": 1, "start_at": start.isoformat(), "end_at": (start + pd.Timedelta(days=7)).isoformat(),
        "start_after_maintenance": 0, "end_reason": "scheduled"}])])
    periods.to_csv(announced / "soloraid_periods.csv", index=False)
    model, _ = web.export(announced, tiers.TierConfig())
    assert model["seasons"][-1]["season"] == 10 and model["seasons"][-1]["bossEn"] == "Next Boss"


def test_the_page_scripts_and_styles_carry_a_content_stamp(site):
    out, summary = site
    local = re.compile(r"""(?:from\s+|import\s*\(\s*|import\s+|href=|src=)["'](\.{0,2}/?[\w./-]+\.(?:js|css)(?:\?[^"']*)?)["']""")
    references = [ref for path in out.rglob("*") if path.suffix in (".html", ".js")
                  for ref in local.findall(path.read_text(encoding="utf-8"))]
    assert references, "the page loads no local script or stylesheet?"
    assert all(ref.endswith(f"?v={summary['code_version']}") for ref in references), references


def test_the_build_is_deterministic(world_dir, tmp_path):
    directory, _ = world_dir
    first = web.build(tmp_path / "a", data_dir=directory, config=tiers.TierConfig())
    second = web.build(tmp_path / "b", data_dir=directory, config=tiers.TierConfig())
    assert first["data_version"] == second["data_version"]
    for name in ("model.json", "decks.json"):
        assert (tmp_path / "a" / "data" / name).read_bytes() == (tmp_path / "b" / "data" / name).read_bytes()


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_time_axis_flags_each_anniversary_on_its_raid():
    """The strip's anniversary flags: each on the raid open on the day, else the first to open within three
    weeks - up to the last season with a start, the live one included; a raid past the three weeks is none."""
    seasons = [(1, "2023-05-11T12:00+09:00", "2023-05-18T04:59:59+09:00"),
               (7, "2023-11-09T12:00+09:00", "2023-11-16T04:59:59+09:00"),
               (13, "2024-05-02T12:00+09:00", "2024-05-09T04:59:59+09:00"),
               (19, "2024-10-31T12:00+09:00", "2024-11-17T05:00:00+09:00"),
               (25, "2025-05-08T12:00+09:00", "2025-05-15T04:59:59+09:00"),
               (31, "2025-11-13T12:00+09:00", "2025-11-20T04:59:59+09:00"),
               (36, "2026-04-30T12:00+09:00", "2026-05-07T04:59:59+09:00"),
               (42, "2026-11-05T12:00+09:00", None),
               (43, "2027-06-10T12:00+09:00", None)]
    listed = [{"season": n, "start": web._ms(a), "end": web._ms(b)} for n, a, b in seasons]
    script = ("const { anniversaries } = await import(process.argv[1]);"
              "const [launch, seasons] = JSON.parse(process.argv[2]);"
              "console.log(JSON.stringify(anniversaries(launch, seasons)));")
    done = subprocess.run([NODE, "--input-type=module", "-e", script, (REPO / "web/js/views/when.js").as_uri(),
                           json.dumps([web._ms(web.LAUNCH), listed])], capture_output=True, text=True,
                          check=True, timeout=60)
    assert [(p["label"], p["season"]) for p in json.loads(done.stdout)] == [
        ("0.5주년", 1), ("1주년", 7), ("1.5주년", 13), ("2주년", 19), ("2.5주년", 25), ("3주년", 31),
        ("3.5주년", 36), ("4주년", 42)]  # 4.5주년's raid (S43) opens five weeks after the day


def test_a_missing_ranking_table_is_a_clear_error(world_dir, tmp_path):
    directory, _ = world_dir
    bare = tmp_path / "processed"
    shutil.copytree(directory, bare)
    (bare / "raid_entries.csv").unlink()
    with pytest.raises(RuntimeError, match="nikke build raids"):
        web.export(bare)


# --------------------------------------------------------------------------
# the page computes what the pipeline does


def js_params(config: tiers.TierConfig, servers: list[str]) -> dict:
    kept = [s for s in servers if (not config.servers or s in config.servers) and s not in config.exclude_servers]
    return {
        "servers": kept, "topN": config.top_n, "rankWeighting": config.rank_weighting,
        "cuts": [[label, value] for label, value in config.cuts],
        "overallCuts": [[label, value] for label, value in config.overall_cuts], "halfLifeDays": config.half_life_days,
        "priorStrength": config.prior_strength, "overall": config.overall,
        "minElementsObserved": config.min_elements_observed, "includeLive": config.include_live,
        "minTier": config.min_tier, "retireAfterDays": config.retire_after_days,
        "retireAfterOwnSeasons": config.retire_after_own_seasons,
        "leftAfter": config.left_after, "generalityBands": list(config.generality_bands),
    }


def run_page(site_dir: Path, params: dict) -> dict:
    done = subprocess.run([NODE, str(DUMP), str(site_dir), json.dumps(params)], capture_output=True, text=True,
                          check=True, timeout=120)
    return json.loads(done.stdout)


def _table(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"unit_id": str}, keep_default_na=False, na_values=[""])


def _close(py: pd.Series, js: pd.Series, what: str, atol: float = 2e-6) -> None:
    a = pd.to_numeric(py, errors="coerce").to_numpy(dtype=float)
    b = pd.to_numeric(js, errors="coerce").to_numpy(dtype=float)
    bad = ~np.isclose(a, b, atol=atol, rtol=0, equal_nan=True)
    assert not bad.any(), f"{what}: {int(bad.sum())} differ, e.g. python {a[bad][:5]} vs page {b[bad][:5]}"


def _same(py: pd.Series, js: pd.Series, what: str) -> None:
    a = py.fillna("").astype(str).str.replace(r"\.0$", "", regex=True).to_numpy()
    b = js.fillna("").astype(str).str.replace(r"\.0$", "", regex=True).to_numpy()
    bad = a != b
    assert not bad.any(), f"{what}: {int(bad.sum())} differ, e.g. python {a[bad][:5]} vs page {b[bad][:5]}"


def _flags(py: pd.Series, js: pd.Series, what: str) -> None:
    truthy = lambda s: s.map(lambda v: str(v).lower() in ("true", "1"))  # noqa: E731
    _same(truthy(py), truthy(js), what)


def compare(tables: Path, page: dict) -> None:
    """Every number the page shows against the pipeline's tables in ``tables``."""
    usage = _table(tables / "metrics_unit_season.csv")
    rows = pd.DataFrame(page["rows"])
    both = usage.merge(rows, on=["season", "unit_id"], how="outer", suffixes=("_py", "_js"), indicator=True)
    assert (both["_merge"] == "both").all(), both.loc[both["_merge"] != "both", ["season", "unit_id", "_merge"]]
    for column in ("lift", "presence", "credit", "deck_share", "main_deck_rate", "avg_deck", "usage_rate", "overall",
                   "element_lift", "generality"):
        _close(both[f"{column}_py"], both[f"{column}_js"], f"season rows: {column}")
    for column in ("rankers", "best_rank", "usage_rank", "in_deck_1", "in_deck_2", "in_deck_3", "in_deck_4",
                   "in_deck_5", "tier", "overall_tier", "element_tier", "element_seasons", "elements_observed"):
        _same(both[f"{column}_py"], both[f"{column}_js"], f"season rows: {column}")
    for column in ("treasure", "element_match", "provisional"):
        _flags(both[f"{column}_py"], both[f"{column}_js"], f"season rows: {column}")

    seasons = _table(tables / "metrics_seasons.csv")
    mine = pd.DataFrame(page["seasons"])
    assert list(seasons["season"]) == list(mine["season"])
    _same(seasons["rankers"], mine["rankers"], "seasons: rankers")
    _same(seasons["decks"], mine["decks"], "seasons: decks")
    _flags(seasons["final"], mine["final"], "seasons: final")

    overall = _table(tables / "metrics_overall_tiers.csv")
    theirs = pd.DataFrame(page["overall"])
    assert list(overall["unit_id"]) == list(theirs["unit_id"]), "overall table: order"
    _close(overall["overall"], theirs["overall"], "overall table: overall")
    _close(overall["generality"], theirs["generality"], "overall table: generality")
    for column in ("overall_rank", "overall_tier", "elements_observed", "seasons_observed", "last_season",
                   "generality_band", "other_used", "last_other", "other_since", "own_after", "path"):
        _same(overall[column], theirs[column], f"overall table: {column}")
    for column in ("provisional", "treasure"):
        _flags(overall[column], theirs[column], f"overall table: {column}")

    life = overall.merge(pd.DataFrame(page["life"]), on="unit_id", how="left", suffixes=("_py", "_js"))
    for column in ("first_used", "run_from", "last_used", "seasons_used", "seasons_out", "returns", "missed_own"):
        _same(life[f"{column}_py"], life[f"{column}_js"], f"overall table: {column}")
    _close(life["idle_days_py"], life["idle_days_js"], "overall table: idle_days")
    _flags(life["retired_py"], life["retired_js"], "overall table: retired")

    elements = _table(tables / "metrics_element_tiers.csv")
    theirs = pd.DataFrame(page["elements"])
    assert list(zip(elements["element"], elements["unit_id"])) == list(zip(theirs["element"], theirs["unit_id"])), \
        "element tables: order"
    _close(elements["element_lift"], theirs["element_lift"], "element tables: element_lift")
    for column in ("element_rank", "element_tier", "element_seasons", "source"):
        _same(elements[column], theirs[column], f"element tables: {column}")
    _flags(elements["treasure"], theirs["treasure"], "element tables: treasure")


def compare_lives(tables: Path, page: dict, config: tiers.TierConfig) -> pd.DataFrame:
    """Every unit's lifespan as each finished season ended, the pipeline's (from its tables in
    ``tables``) against the page's. Returns the pipeline's."""
    usage = _table(tables / "metrics_unit_season.csv")
    seasons = _table(tables / "metrics_seasons.csv")
    for column in ("start_at", "end_at", "collected_on", "collected_until"):
        seasons[column] = pd.to_datetime(seasons[column], utc=True)
    ours = pd.concat([tiers.lifespans(usage, seasons, end, config).assign(season=season)
                      for season, end in seasons.loc[seasons["final"], ["season", "end_at"]].itertuples(index=False)])
    both = ours.astype(object).merge(pd.DataFrame(page["lives"]), on=["season", "unit_id"], how="outer",
                                     suffixes=("_py", "_js"), indicator=True)
    assert (both["_merge"] == "both").all(), both.loc[both["_merge"] != "both", ["season", "unit_id", "_merge"]]
    for column in ("first_used", "run_from", "last_used", "seasons_used", "seasons_out", "returns", "missed_own"):
        _same(both[f"{column}_py"], both[f"{column}_js"], f"lifespans: {column}")
    _close(both["idle_days_py"], both["idle_days_js"], "lifespans: idle_days")
    _flags(both["retired_py"], both["retired_js"], "lifespans: retired")
    return ours


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("name", list(CONFIGS))
def test_the_page_computes_what_the_pipeline_does(name, world_dir, site, tmp_path):
    directory, world = world_dir
    out, _ = site
    config = tiers.TierConfig(**CONFIGS[name])
    pipeline.run(data_dir=directory, config=config, out_dir=tmp_path)
    page = run_page(out, js_params(config, ordered(world.entries["server"].unique())))
    compare(tmp_path, page)
    lives = compare_lives(tmp_path, page, config)
    if name == "defaults":
        # somewhere along the way units sat out a season of their own element, and one retired for it
        assert (lives["missed_own"] > 0).any() and lives["retired"].any()
        # the treasure and the added elements took part
        rows = pd.DataFrame(page["rows"])
        assert rows["treasure"].any()
        assert set(pd.DataFrame(page["elements"]).query("source == 'skill'")["element"]) == {"Water", "Iron"}
        # the element dealers are specialists by generality, the supports that go anywhere generalists
        overall = pd.DataFrame(page["overall"]).set_index("unit_id")
        assert set(overall.loc[list(world.element_dps.values()), "generality_band"]) == {"specialist"}
        assert set(overall.loc[world.universal, "generality_band"]) == {"generalist"}
        assert set(overall.loc[world.universal, "path"]) == {"generalist"}
