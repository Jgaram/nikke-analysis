"""Treasures (애장품): read from update notices, and a unit's tiers reckoned apart
before and after its treasure while its record stays one line."""

from datetime import datetime

import pandas as pd
import pytest

from nikke_analysis.analyze import pipeline, tiers
from nikke_analysis.build import releases, treasures
from nikke_analysis.build.notices import Notice
from nikke_analysis.build.roster import build_alias_rows, merge_roster
from nikke_analysis.tierlist import TierBook, render, render_unit
from nikke_analysis.timeline import Timeline
from nikke_analysis.util.kdate import KST
from nikke_analysis.util.names import build_name_index
from nikke_analysis.viz import charts
from nikke_analysis.viz import icons as icon_art
from tests.synthetic import make_world, write_processed

ROSTER = [
    {"unit_id": "100", "name_ko": "라플라스"},
    {"unit_id": "072", "name_ko": "디젤"},
    {"unit_id": "075", "name_ko": "디젤 : 윈터 스위츠"},
    {"unit_id": "112", "name_ko": "바이퍼"},
    {"unit_id": "352", "name_ko": "헬름"},
    {"unit_id": "032", "name_ko": "미란다"},
]


def notice(text, title, kind_title=None, published=datetime(2025, 1, 13, 17, 30, tzinfo=KST)):
    return Notice(f"official:{title}", "official", published, None, kind_title or title, "", text.strip())


def extract(text, title="1월 16일 업데이트 공지", **kwargs):
    matcher = releases.UnitMatcher(build_name_index(ROSTER))
    return treasures.extract(notice(text, title, **kwargs), matcher)


# --------------------------------------------------------------------------
# reading the notices
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "line, names",
    [
        ("애장품이 추가되는 니케 : 라플라스, 엑시아, 프림, 디젤", ["라플라스", "엑시아", "프림", "디젤"]),
        ("6.1 신규 애장품 니케: 바이퍼가 추가됩니다..", ["바이퍼가"]),
        ("① 애장품 추가 니케 : [헬름], [미란다], [드레이크], [밀크]", ["헬름", "미란다", "드레이크", "밀크"]),
        ("▶ 애장품 추가 니케 : [팬텀], [슈가], [로산나], [플로라]", ["팬텀", "슈가", "로산나", "플로라"]),
    ],
)
def test_every_shape_of_the_treasure_line_lists_its_units(line, names):
    match = treasures.LINE_RE.search(line)
    assert match is not None
    assert treasures.listed_names(match.group("names")) == names


@pytest.mark.parametrize(
    "line",
    [
        "마일리지 상점에서 골드 마일리지 티켓으로 애장품 니케 선택 상자를 교환하실 수 있습니다.",
        "▶ 애장품 기능 개방 조건 : 메인 챕터 6-4 클리어",
        "- 파견과 솔로 레이드에서 바이퍼의 애장품 재료를 획득할 수 있습니다.",
    ],
)
def test_other_treasure_sentences_name_no_units(line):
    assert treasures.LINE_RE.search(line) is None


def test_an_update_brings_its_treasures_on_its_day():
    found = extract("""
4. 신규 콘텐츠
4.1 신규 애장품 추가
① 애장품 추가 니케 : [헬름], [미란다]
② 애장품 기능 개방 조건 : 메인 챕터 6-4 클리어
""")
    assert [(t.unit_id, t.name) for t in found] == [("352", "헬름"), ("032", "미란다")]
    assert {t.treasure_at for t in found} == {"2025-01-16T00:00:00+09:00"}  # the update's day, after maintenance
    assert all(t.after_maintenance == 1 for t in found)


def test_a_closing_particle_is_not_part_of_the_name():
    [found] = extract("6.1 신규 애장품 니케: 바이퍼가 추가됩니다..", "7월 4일 업데이트 공지",
                      published=datetime(2024, 7, 4, 6, 54, tzinfo=KST))
    assert (found.unit_id, found.name, found.treasure_date) == ("112", "바이퍼", "2024-07-04")


def test_a_base_name_is_not_its_variant():
    [found] = extract("애장품이 추가되는 니케 : 디젤", "5월 30일 업데이트 공지")
    assert found.unit_id == "072"


def test_only_update_notices_release_treasures():
    """A developer note previewing next year's treasures is a plan, not a release."""
    assert extract("애장품 추가 니케 : [헬름]", "【개발자 노트】2025년 1월") == []


def test_an_unknown_name_is_kept_unresolved_not_guessed():
    [found] = extract("애장품 추가 니케 : [누군가]")
    assert (found.unit_id, found.name) == ("", "누군가")


def test_the_earliest_update_wins():
    later = extract("애장품 추가 니케 : [헬름]", "2월 20일 업데이트 공지")
    first = extract("애장품 추가 니케 : [헬름]", "1월 16일 업데이트 공지")
    [kept] = treasures.first_treasures(later + first)
    assert kept.treasure_date == "2025-01-16"


# --------------------------------------------------------------------------
# the roster and the tier split
# --------------------------------------------------------------------------

def test_the_roster_says_when_the_treasure_came():
    gamefiles = [{"unit_id": "140", "name_en": "Sugar", "name_ko": "슈가", "name_ja": "シュガー"}]
    utils = [{"unit_id": "140", "name_en": "Sugar", "element": "Iron", "burst": "I", "unit_class": "Defender",
              "rarity": "SSR", "datafile_added": "2022-04-11"}]
    roster = merge_roster(
        gamefiles, utils, launch_covered=True,
        treasures={"140": {"treasure_at": "2026-07-23T00:00:00+09:00", "treasure_date": "2026-07-23"}},
    )
    [unit] = roster  # still one unit, under its own name
    assert (unit.unit_id, unit.name_ko, unit.treasure_at) == ("140", "슈가", "2026-07-23T00:00:00+09:00")
    assert {row["alias"] for row in build_alias_rows(roster)} >= {"Sugar", "슈가"}


def _one_unit(lifts, treasure):
    """One Fire unit over seasons 1..n, Fire-weak each, played with its treasure where ``treasure``."""
    n = len(lifts)
    ends = [pd.Timestamp("2025-01-08T00:00:00Z") + pd.Timedelta(days=30 * i) for i in range(n)]
    table = pd.DataFrame({"season": range(1, n + 1), "unit_id": "a", "lift": lifts, "element": "Fire",
                          "extra_elements": "", "treasure": treasure})
    seasons = pd.DataFrame({"season": range(1, n + 1), "end_at": ends, "weak_element": "Fire", "final": True,
                            "collected_on": ends})
    return table, seasons, ends


def test_a_view_stands_on_one_side_of_the_treasure():
    table, seasons, ends = _one_unit([2.0, 2.0, 0.5], [False, False, True])
    after = ends[-1] + pd.Timedelta(days=1)
    with_it = tiers.standings(table, seasons, after, treasured=["a"])
    without = tiers.standings(table, seasons, after, treasured=[])
    assert with_it.elements.iloc[0]["element_lift"] == pytest.approx(0.5)  # only the season with it
    assert with_it.elements.iloc[0]["element_seasons"] == 1 and bool(with_it.overall.iloc[0]["treasure"])
    assert without.elements.iloc[0]["element_seasons"] == 2 and not bool(without.overall.iloc[0]["treasure"])
    # by default a unit has its treasure once a counted season was played with it
    assert tiers.standings(table, seasons, after).elements.iloc[0]["element_seasons"] == 1


def test_right_after_the_treasure_a_unit_has_no_tier_yet():
    table, seasons, ends = _one_unit([2.0, 2.0, 0.5], [False, False, True])
    gap = ends[1] + pd.Timedelta(days=1)  # the treasure is out, no season played with it yet
    assert tiers.standings(table, seasons, gap, treasured=["a"]).overall.empty


def test_the_heart_is_a_mark_of_its_own():
    mark = icon_art.heart(16)
    assert mark.shape == (16, 16, 4)
    red = mark[..., 0] - mark[..., 1]
    assert red[8, 8] > 0.5 and mark[0, 0, 3] == 0.0  # red at the centre, clear in the corner


# --------------------------------------------------------------------------
# through the pipeline
# --------------------------------------------------------------------------

TREASURE_SEASON = 5  # the first season played with the treasure


@pytest.fixture(scope="module")
def world_with_treasure(tmp_path_factory):
    """The synthetic world where the Water dealer gets its treasure a week before season 5,
    and the treasure's skill adds Wind (Wind-weak seasons: 3 before it, 8 after)."""
    directory = tmp_path_factory.mktemp("treasure")
    world = make_world(seasons=8, rankers=15, fillers=24, seed=11)
    unit = world.element_dps["Water"]
    start = pd.Timestamp(world.seasons.set_index("season").loc[TREASURE_SEASON, "start_at"])
    at = (start - pd.Timedelta(days=7)).normalize()
    world.roster["treasure_at"] = ""
    world.roster.loc[world.roster["unit_id"] == unit, "treasure_at"] = at.isoformat()
    world.roster["treasure_elements"] = world.roster["unit_id"].map({unit: "Wind"}).fillna("")
    write_processed(world, directory)
    notice = (at - pd.Timedelta(days=3)).isoformat()
    pd.DataFrame([{"unit_id": unit, "name": "Water Dealer", "treasure_at": at.isoformat(),
                   "treasure_date": at.date().isoformat(), "after_maintenance": 1, "notice_id": "official:t",
                   "notice_title": "업데이트 공지", "notice_published_at": notice, "evidence": ""}]
                 ).to_csv(directory / "treasures.csv", index=False)
    pipeline.run(data_dir=directory)
    return directory, world, unit, at


def _history(directory):
    return pd.read_csv(directory / "metrics_unit_season.csv", dtype={"unit_id": str})


def test_the_seasons_played_with_the_treasure_are_flagged(world_with_treasure):
    directory, world, unit, _ = world_with_treasure
    rows = _history(directory).query("unit_id == @unit").sort_values("season")
    assert list(rows["season"]) == list(range(1, 9))  # one unit, one line
    assert list(rows["treasure"]) == [s >= TREASURE_SEASON for s in range(1, 9)]
    assert not _history(directory).query("unit_id != @unit")["treasure"].any()


def test_each_season_is_tiered_on_its_own_side(world_with_treasure):
    """Water-weak seasons are 2 and 7: in 7 the element tier stands on 7 alone."""
    directory, world, unit, _ = world_with_treasure
    rows = _history(directory).query("unit_id == @unit").set_index("season")
    assert rows.loc[2, "element_seasons"] == 1 and rows.loc[7, "element_seasons"] == 1
    # the overall at the first season with the treasure knows only that season
    assert rows.loc[TREASURE_SEASON, "overall"] != rows.loc[TREASURE_SEASON - 1, "overall"]


def test_the_step_into_the_treasure_is_a_tier_change(world_with_treasure):
    directory, world, unit, _ = world_with_treasure
    changes = pd.read_csv(directory / "metrics_tier_changes.csv", dtype={"unit_id": str})
    marked = changes[changes["treasure"]]
    assert list(zip(marked["unit_id"], marked["season_to"])) == [(unit, TREASURE_SEASON)]


def test_a_view_of_a_moment_takes_the_side_the_unit_was_on(world_with_treasure):
    directory, world, unit, at = world_with_treasure
    book = TierBook.load(directory)
    name = world.roster.set_index("unit_id").loc[unit, "name_ko"]
    before = book.unit(name, (at - pd.Timedelta(days=1)).to_pydatetime())
    gap = book.unit(name, (at + pd.Timedelta(days=1)).to_pydatetime())
    after = book.unit(name, "2026-01-01")
    assert not before.treasured and before.profile["seasons_observed"] == TREASURE_SEASON - 1
    assert gap.treasured and gap.profile is None
    assert unit not in set(book.at((at + pd.Timedelta(days=1)).to_pydatetime()).overall["unit_id"])
    assert after.treasured and after.profile["seasons_observed"] == 8 - TREASURE_SEASON + 1
    assert after.profile["treasure"]


def test_the_unit_is_shown_by_its_name_and_its_record_is_one_line(world_with_treasure):
    directory, world, unit, at = world_with_treasure
    book = TierBook.load(directory)
    name = world.roster.set_index("unit_id").loc[unit, "name_ko"]
    history = book.unit(name, "2026-01-01")
    assert list(history.rows["season"]) == list(range(1, 9))
    text = render_unit(history, book.config)
    lines = text.splitlines()
    marker = next(i for i, line in enumerate(lines) if line.lstrip().startswith("♥"))
    assert lines[marker - 1].split()[0] == str(TREASURE_SEASON - 1)
    assert lines[marker + 1].split()[0] == str(TREASURE_SEASON)
    assert f"애장품 {at:%Y-%m-%d}" in lines[0]
    assert "♥" not in render(book.at("2026-01-01"))  # the unit itself carries no mark


def test_the_unit_view_counts_the_treasures_element_from_the_treasure_on(world_with_treasure):
    directory, world, unit, at = world_with_treasure
    book = TierBook.load(directory)
    name = world.roster.set_index("unit_id").loc[unit, "name_ko"]
    before = book.unit(name, (at - pd.Timedelta(days=1)).to_pydatetime())
    after = book.unit(name, "2026-01-01")
    assert before.elements == ("Water",) and after.elements == ("Water", "Wind")
    assert [e["element"] for e in after.profile["elements"]] == ["Water", "Wind"]
    lines = render_unit(after, book.config).splitlines()
    assert "애장품 스킬로 풍압 우월 코드" in lines[0]
    rows = {int(line.split()[0]): line for line in lines if line.split() and line.split()[0].isdigit()}
    assert "▶풍압" in rows[8] and "▶풍압" not in rows[3] and "▶수냉" in rows[2]


def test_the_timeline_lists_treasures_but_keeps_one_unit(world_with_treasure):
    directory, world, unit, at = world_with_treasure
    timeline = Timeline.load(directory)
    announced = timeline.at((at - pd.Timedelta(days=1)).to_pydatetime())
    came = timeline.at((at + pd.Timedelta(days=1)).to_pydatetime())
    assert [u.unit_id for u in announced.announced_treasures] == [unit]
    assert [u.unit_id for u in came.treasured_within(30)] == [unit] and not came.announced_treasures
    assert len(announced.units) == len(came.units)


def test_the_charts_mark_the_treasure_on_the_units_line(world_with_treasure, tmp_path):
    directory, world, unit, _ = world_with_treasure
    name = world.roster.set_index("unit_id").loc[unit, "name_en"]
    result = charts.render_all(data_dir=directory, out_dir=tmp_path, themes=("light",), units=[name])
    assert {"tier-trajectories", "tier-heatmap"} <= set(result["written"])
