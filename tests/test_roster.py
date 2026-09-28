import textwrap

from nikke_analysis.build.roster import (
    load_extra_elements,
    merge_roster,
    parse_gamefiles_role,
    parse_nikkeutils,
    build_alias_rows,
)

ROLE_YAML = textwrap.dedent(
    """
    ---
    16_name:
      en: 'Rapi: Red Hood'
      ko: '라피 : 레드 후드'
      ja: ラピ：レッドフード
    c016_description:
      en: Something long
    """
).encode()

CHARACTERS_JS = """
const characters = [
    { id: 1, character_id: "c010_00", name: "Rapi", rarity: "SR", burst: "II", element: "Fire",
      manufacturer: "Elysion", class: "Attacker", weapon: "Assault Rifle", squad: "Counters",
      dateAdded: "2022-04-11" },
    { id: 2, character_id: "c016_00", name: "Rapi: Red Hood", rarity: "SSR", burst: "III",
      element: "Fire", manufacturer: "Pilgrim", class: "Attacker", weapon: "Assault Rifle",
      squad: "Counters", dateAdded: "2023-11-16" },
];
"""


def test_role_yaml_gives_id_and_three_languages():
    row = parse_gamefiles_role("roledata/[016] Rapi: Red Hood.yaml", ROLE_YAML)
    assert row == {
        "unit_id": "016",
        "name_en": "Rapi: Red Hood",
        "name_ko": "라피 : 레드 후드",
        "name_ja": "ラピ：レッドフード",
    }


def test_role_file_without_bracket_id_is_skipped():
    assert parse_gamefiles_role("roledata/notes.yaml", ROLE_YAML) is None


def test_nikkeutils_maps_character_id_to_unit_id():
    rows = parse_nikkeutils(CHARACTERS_JS)
    assert [r["unit_id"] for r in rows] == ["010", "016"]
    assert rows[1]["unit_class"] == "Attacker"
    assert rows[1]["datafile_added"] == "2023-11-16"


def test_merge_prefers_gamefile_names_and_keeps_attributes():
    roster = merge_roster(
        [{"unit_id": "016", "name_en": "Rapi: Red Hood", "name_ko": "라피 : 레드 후드", "name_ja": ""}],
        parse_nikkeutils(CHARACTERS_JS),
    )
    by_id = {u.unit_id: u for u in roster}
    assert by_id["016"].name_ko == "라피 : 레드 후드"
    assert by_id["016"].element == "Fire"
    assert by_id["016"].is_variant == 1
    assert by_id["016"].base_name_en == "Rapi"
    # present in only one source, still emitted
    assert by_id["010"].in_gamefiles == 0 and by_id["010"].in_nikkeutils == 1


def test_release_date_precedence_and_confidence():
    gamefiles = [{"unit_id": "010", "name_en": "Rapi"}, {"unit_id": "016", "name_en": "Rapi: Red Hood"}]
    roster = merge_roster(
        gamefiles,
        parse_nikkeutils(CHARACTERS_JS),
        overrides={"010": {"release_date": "2022-11-04", "reason": "global launch"}},
        patch_releases={"016": "2023-11-16"},
    )
    by_id = {u.unit_id: u for u in roster}
    assert (by_id["010"].release_date, by_id["010"].release_date_source) == ("2022-11-04", "manual")
    assert by_id["010"].release_date_confidence == "high"
    assert by_id["016"].release_date_source == "patchnote"


def test_skill_elements_come_from_the_hand_kept_table(tmp_path):
    path = tmp_path / "extra_elements.csv"
    path.write_text(
        "unit_id,element,reason\n"
        "16,철갑,스킬로 철갑 우월 코드\n"
        "016,Iron,같은 줄을 두 번 적어도 한 번\n"
        "140,water,스킬로 수냉 우월 코드\n"
        "999,불,속성 이름이 아니면 건너뛴다\n",
        encoding="utf-8",
    )
    assert load_extra_elements(path) == {"016": ("Iron",), "140": ("Water",)}
    assert load_extra_elements(tmp_path / "missing.csv") == {}


def test_an_element_the_treasure_adds_is_kept_apart(tmp_path):
    path = tmp_path / "extra_elements.csv"
    path.write_text(
        "unit_id,element,since,reason\n"
        "016,Iron,,스킬로 철갑 우월 코드\n"
        "140,Water,treasure,애장품 스킬로 수냉 우월 코드\n"
        "170,풍압,애장품,한국어로 적어도 된다\n"
        "200,Fire,someday,모르는 since 는 건너뛴다\n",
        encoding="utf-8",
    )
    assert load_extra_elements(path) == {"016": ("Iron",)}
    assert load_extra_elements(path, "treasure") == {"140": ("Water",), "170": ("Wind",)}


def test_the_roster_carries_skill_elements_but_not_the_units_own():
    roster = merge_roster(
        [{"unit_id": "016", "name_en": "Rapi: Red Hood"}],
        parse_nikkeutils(CHARACTERS_JS),
        extra_elements={"016": ("Iron", "Fire")},
    )
    by_id = {u.unit_id: u for u in roster}
    assert (by_id["016"].element, by_id["016"].extra_elements) == ("Fire", "Iron")
    assert by_id["010"].extra_elements == ""


def test_the_roster_carries_the_treasures_elements_in_a_column_of_their_own():
    roster = merge_roster(
        [{"unit_id": "016", "name_en": "Rapi: Red Hood"}],
        parse_nikkeutils(CHARACTERS_JS),
        extra_elements={"016": ("Iron",)},
        treasure_elements={"016": ("Water", "Iron", "Fire")},
    )
    by_id = {u.unit_id: u for u in roster}
    assert (by_id["016"].extra_elements, by_id["016"].treasure_elements) == ("Iron", "Water")
    assert by_id["010"].treasure_elements == ""


def test_datafile_date_is_marked_low_confidence():
    roster = merge_roster([], parse_nikkeutils(CHARACTERS_JS))
    assert all(u.release_date_source.startswith("datafile") for u in roster)
    assert all(u.release_date_confidence == "low" for u in roster)


def test_alias_rows_include_variant_suffixes():
    roster = merge_roster(
        [{"unit_id": "016", "name_en": "Rapi: Red Hood", "name_ko": "라피 : 레드 후드"}], []
    )
    aliases = {(r["alias"], r["kind"]) for r in build_alias_rows(roster)}
    assert ("Rapi: Red Hood", "full") in aliases
    assert ("Red Hood", "variant_suffix") in aliases
    assert ("레드 후드", "variant_suffix") in aliases


def test_pre_launch_datafile_dates_are_clamped_to_the_global_launch():
    """The launch roster's data-file dates are beta dates from seven months early."""
    from nikke_analysis.build.roster import GLOBAL_LAUNCH_DATE

    roster = merge_roster([], parse_nikkeutils(CHARACTERS_JS))
    by_id = {u.unit_id: u for u in roster}
    assert by_id["010"].datafile_added == "2022-04-11"
    assert by_id["010"].release_date == GLOBAL_LAUNCH_DATE
    assert by_id["010"].release_date_source == "datafile_floored"
    # A post-launch date is left alone.
    assert by_id["016"].release_date == "2023-11-16"
    assert by_id["016"].release_date_source == "datafile"


COLLAB_YAML = textwrap.dedent(
    """
    ---
    836_name:
      en: Sakura
      ko: 사쿠라
      ja: サクラ
    c836_description:
      en: |-
        Her full name is Sakura Suzuhara.
        She holds the rank of second lieutenant.
      ko: |-
        풀네임은 스즈하라 사쿠라.
        카츠라기 미사토가 이끄는 조직 [WILLE]의 소위이면서 의무관이다.
    """
).encode()


def test_a_collaboration_unit_keeps_its_full_name():
    row = parse_gamefiles_role("roledata/[836] Sakura.yaml", COLLAB_YAML)
    assert row["full_name_ko"] == "스즈하라 사쿠라"
    assert row["full_name_en"] == "Sakura Suzuhara"


def test_full_names_become_aliases_including_expanded_variants():
    roster = merge_roster(
        [
            {"unit_id": "831", "name_ko": "레이", "full_name_ko": "아야나미 레이"},
            {"unit_id": "834", "name_ko": "레이 (가칭)"},
            {"unit_id": "870", "name_ko": "퀸(마코토)", "full_name_ko": "니지마 마코토"},
        ],
        [],
    )
    aliases = {(r["unit_id"], r["alias"], r["kind"]) for r in build_alias_rows(roster)}
    assert ("831", "아야나미 레이", "full_name") in aliases
    # How the update notices name them.
    assert ("834", "아야나미 레이 (가칭)", "full_name_variant") in aliases
    assert ("870", "퀸(니지마 마코토)", "full_name_variant") in aliases


def test_launch_units_need_notice_coverage_of_the_launch():
    gamefiles = [{"unit_id": "010", "name_en": "Rapi"}, {"unit_id": "016", "name_en": "Rapi: Red Hood"}]
    covered = {u.unit_id: u for u in merge_roster(gamefiles, parse_nikkeutils(CHARACTERS_JS), launch_covered=True)}
    assert (covered["010"].release_date, covered["010"].release_date_source) == ("2022-11-04", "launch")
    assert covered["010"].release_date_confidence == "medium"
    # A post-launch unit no notice introduced stays a low-confidence data-file date.
    assert covered["016"].release_date_source == "datafile"


def test_patch_note_release_carries_its_instant():
    roster = merge_roster(
        [{"unit_id": "016", "name_en": "Rapi: Red Hood"}],
        parse_nikkeutils(CHARACTERS_JS),
        patch_releases={"016": "2025-01-01"},
        release_times={"016": "2025-01-01T00:00:00+09:00"},
    )
    by_id = {u.unit_id: u for u in roster}
    assert by_id["016"].release_at == "2025-01-01T00:00:00+09:00"
    assert by_id["016"].release_date_confidence == "high"


def test_enikk_fills_what_nikkeutils_does_not_have_yet():
    enikk = [{"unit_id": "404", "name_en": "Guilty: Mighty Bunny", "rarity": "SSR", "burst": "III",
              "element": "Water", "manufacturer": "Missilis Industry", "unit_class": "Attacker",
              "weapon": "Sniper Rifle", "squad": "Real Kindness"}]
    roster = merge_roster([{"unit_id": "404", "name_ko": "길티 : 마이티 바니"}], [], enikk=enikk)
    unit = roster[0]
    assert (unit.element, unit.burst, unit.weapon, unit.in_enikk) == ("Water", "III", "Sniper Rifle", 1)
