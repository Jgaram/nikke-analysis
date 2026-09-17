import textwrap

from nikke_analysis.build.roster import (
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
