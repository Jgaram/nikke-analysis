"""Treasures (애장품): read from update notices, and the unit a treasure makes
counted as a unit of its own from then on (``221♥``)."""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from nikke_analysis.analyze import metrics, pipeline, tiers
from nikke_analysis.build import raids, releases, treasures
from nikke_analysis.build.notices import Notice
from nikke_analysis.build.roster import build_alias_rows, merge_roster
from nikke_analysis.tierlist import TierBook, find_unit, render_unit
from nikke_analysis.timeline import Timeline
from nikke_analysis.util.kdate import KST
from nikke_analysis.util.names import build_name_index, mark_treasure, treasure_base, treasure_id
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
# the unit a treasure makes
# --------------------------------------------------------------------------

def test_the_mark_and_its_words():
    assert treasure_id("100") == "100♥" and treasure_base("100♥") == "100" and treasure_base("100") is None
    for query in ("라플라스 애장품", "라플라스(애장품)", "라플라스♡", "라플라스 ♥", "Laplace treasure"):
        assert mark_treasure(query).endswith("♥"), query
    assert mark_treasure("애장품") == "애장품"  # nothing left to mark
    assert mark_treasure("라플라스") == "라플라스"


def test_the_roster_gets_the_treasure_unit_beside_its_base():
    gamefiles = [{"unit_id": "140", "name_en": "Sugar", "name_ko": "슈가", "name_ja": "シュガー"}]
    utils = [{"unit_id": "140", "name_en": "Sugar", "element": "Iron", "burst": "I", "unit_class": "Defender",
              "rarity": "SSR", "datafile_added": "2022-04-11"}]
    roster = merge_roster(
        gamefiles, utils, extra_elements={"140": ("Water",)}, launch_covered=True,
        treasures={"140": {"treasure_at": "2026-07-23T00:00:00+09:00", "treasure_date": "2026-07-23"}},
    )
    by_id = {u.unit_id: u for u in roster}
    base, marked = by_id["140"], by_id["140♥"]
    assert base.treasure_at == "2026-07-23T00:00:00+09:00" and not base.treasure_of
    assert (marked.name_ko, marked.name_en, marked.name_ja) == ("슈가♥", "Sugar♥", "シュガー♥")
    assert (marked.element, marked.extra_elements, marked.burst) == ("Iron", "Water", "I")  # tiered in both, like the base
    assert (marked.release_at, marked.release_date_source, marked.release_date_confidence) == (
        "2026-07-23T00:00:00+09:00", "treasure", "high")
    assert marked.treasure_of == "140" and not marked.treasure_at
    # notices and rankings only ever name the base: the alias table has no marked unit
    assert {row["unit_id"] for row in build_alias_rows(roster)} == {"140"}


def test_a_ranked_name_is_the_treasure_unit_from_the_first_season_after_it():
    index = build_name_index([{"unit_id": "352", "name_en": "Helm"}])
    seasons = {21: {"start_at": "2025-01-09T12:00:00+09:00"}, 22: {"start_at": "2025-02-06T12:00:00+09:00"}}
    resolver = raids.UnitResolver(index, seasons=seasons, treasures={"352": "2025-01-16T00:00:00+09:00"})
    # season 21 ended on the update's morning: its record is the base's
    assert resolver.in_season("352", 21) == "352"
    assert resolver.in_season("352", 22) == "352♥"
    assert resolver.in_season("100", 22) == "100"


def test_find_unit_takes_the_mark_or_the_word():
    units = pd.DataFrame({"unit_id": ["100", "100♥", "103"], "name_ko": ["라플라스", "라플라스♥", "라플라스 : 얼티밋 히어로"],
                          "name_en": ["Laplace", "Laplace♥", "Laplace: Ultimate Hero"]})
    index = build_name_index([{"unit_id": "100", "name_ko": "라플라스"}, {"unit_id": "103", "name_ko": "라플라스 : 얼티밋 히어로"}])
    assert find_unit("라플라스", units, index) == "100"
    for query in ("라플라스♥", "라플라스 애장품", "laplace♥", "100♥"):
        assert find_unit(query, units, index) == "100♥", query
    # a season after the treasure has only the unit it became: the base's name finds it
    later = units[units["unit_id"] != "100"]
    assert find_unit("라플라스", later, index) == "100♥"


def test_the_heart_marks_the_corner_of_the_face():
    face = np.zeros((40, 40, 4))
    face[..., :3], face[..., 3] = 0.5, 1.0
    marked = icon_art.with_heart(face)
    assert np.allclose(marked[:10, :10], face[:10, :10])  # the rest of the face is untouched
    red = marked[..., 0] - marked[..., 1]
    assert red[20:, 20:].max() > 0.5 and red[:20, :20].max() < 1e-9
    assert icon_art.heart(16).shape == (16, 16, 4)


# --------------------------------------------------------------------------
# through the pipeline
# --------------------------------------------------------------------------

TREASURE_SEASON = 5  # the first season the treasure unit plays


@pytest.fixture(scope="module")
def world_with_treasure(tmp_path_factory):
    """The synthetic world where the Water dealer gets its treasure between seasons 4 and 5."""
    directory = tmp_path_factory.mktemp("treasure")
    world = make_world(seasons=8, rankers=15, fillers=24, seed=11)
    base = world.element_dps["Water"]
    marked = treasure_id(base)
    start = pd.Timestamp(world.seasons.set_index("season").loc[TREASURE_SEASON, "start_at"])
    at = (start - pd.Timedelta(days=7)).normalize().isoformat()
    roster = world.roster.copy()
    roster["treasure_at"], roster["treasure_of"] = "", ""
    roster.loc[roster["unit_id"] == base, "treasure_at"] = at
    row = roster[roster["unit_id"] == base].iloc[0].copy()
    row["unit_id"], row["name_en"], row["name_ko"] = marked, f"{row['name_en']}♥", f"{row['name_ko']}♥"
    row["release_date"], row["release_at"], row["release_date_source"] = at[:10], at, "treasure"
    row["treasure_at"], row["treasure_of"] = "", base
    world.roster = pd.concat([roster, row.to_frame().T], ignore_index=True)
    entries = world.entries.copy()
    later = (entries["unit_id"] == base) & (entries["season"] >= TREASURE_SEASON)
    entries.loc[later, "unit_id"] = marked  # what build/raids does with the site's name
    world.entries = entries
    write_processed(world, directory)
    pipeline.run(data_dir=directory)
    return directory, world, base, marked


def test_each_season_has_the_base_or_the_treasure_unit_never_both(world_with_treasure):
    directory, world, base, marked = world_with_treasure
    table = pd.read_csv(directory / "metrics_unit_season.csv", dtype={"unit_id": str, "treasure_of": str})
    seasons_of = table.groupby("unit_id")["season"].agg(set)
    assert seasons_of[base] == set(range(1, TREASURE_SEASON))
    assert seasons_of[marked] == set(range(TREASURE_SEASON, 9))
    assert table.loc[table["unit_id"] == marked, "treasure_of"].eq(base).all()


def test_the_tables_of_now_list_the_treasure_unit_not_its_base(world_with_treasure):
    directory, world, base, marked = world_with_treasure
    overall = pd.read_csv(directory / "metrics_overall_tiers.csv", dtype={"unit_id": str})
    elements = pd.read_csv(directory / "metrics_element_tiers.csv", dtype={"unit_id": str})
    assert marked in set(overall["unit_id"]) and base not in set(overall["unit_id"])
    assert base not in set(elements["unit_id"])
    assert overall["overall_rank"].min() == 1 and overall["overall_rank"].max() <= len(overall)


def test_the_standings_leave_out_a_unit_once_its_treasure_is_out():
    table = pd.DataFrame({"season": [1, 1], "unit_id": ["a", "b"], "lift": [2.0, 1.0], "element": ["Fire", "Fire"],
                          "extra_elements": ["", ""]})
    end = pd.Timestamp("2025-01-08T00:00:00Z")
    seasons = pd.DataFrame({"season": [1], "end_at": [end], "weak_element": ["Fire"], "final": [True],
                            "collected_on": [end]})
    replaced = pd.Series([pd.Timestamp("2025-02-01T00:00:00Z")], index=["a"])
    before = tiers.standings(table, seasons, pd.Timestamp("2025-01-20T00:00:00Z"), replaced=replaced)
    after = tiers.standings(table, seasons, pd.Timestamp("2025-02-02T00:00:00Z"), replaced=replaced)
    assert list(before.overall["unit_id"]) == ["a", "b"]
    assert list(after.overall["unit_id"]) == ["b"] and after.overall["overall_rank"].tolist() == [1]


def test_the_pool_swaps_the_base_for_the_treasure_unit(world_with_treasure):
    directory, world, base, marked = world_with_treasure
    timeline = Timeline.load(directory)
    at = pd.Timestamp(world.roster.set_index("unit_id").loc[base, "treasure_at"]).to_pydatetime()
    before = {u.unit_id for u in timeline.units_at(at - pd.Timedelta(hours=1))}
    after = {u.unit_id for u in timeline.units_at(at)}
    assert base in before and marked not in before
    assert marked in after and base not in after and len(after) == len(before)
    assert [u.unit_id for u in timeline.at(at + pd.Timedelta(days=1)).treasured_within(30)] == [marked]


def test_a_units_record_points_to_the_unit_its_treasure_made(world_with_treasure):
    directory, world, base, marked = world_with_treasure
    book = TierBook.load(directory)
    name = world.roster.set_index("unit_id").loc[base, "name_ko"]
    old = book.unit(name, "2026-01-01")
    assert old.unit_id == base and old.successor == f"{name}♥"
    assert old.profile is not None  # where it stood after its last season, not "no record"
    assert "애장품이 나오기 전 마지막 시즌" in render_unit(old, book.config)
    new = book.unit(f"{name} 애장품", "2026-01-01")
    assert new.unit_id == marked and new.base == name
    assert f"{name}의 애장품" in render_unit(new, book.config)
    assert metrics.replacement_instants(world.roster).index.tolist() == [base]
