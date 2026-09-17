from nikke_analysis.util.names import (
    NameIndex,
    build_name_index,
    normalize_name,
    normalize_unit_id,
    variant_suffix,
)

import pytest


ROSTER = [
    {"unit_id": "010", "name_en": "Rapi", "name_ko": "라피", "name_ja": "ラピ"},
    {"unit_id": "016", "name_en": "Rapi: Red Hood", "name_ko": "라피 : 레드 후드", "name_ja": "ラピ：レッドフード"},
    {"unit_id": "015", "name_en": "Anis: Sparkling Summer", "name_ko": "아니스 : 스파클링 서머"},
    {"unit_id": "260", "name_en": "Modernia", "name_ko": "모더니아"},
]


def test_normalize_folds_punctuation_and_case():
    assert normalize_name("Rapi: Red Hood") == normalize_name("rapi red hood") == "rapiredhood"
    assert normalize_name("라피 : 레드 후드") == "라피레드후드"


def test_normalize_unit_id_accepts_every_spelling():
    assert normalize_unit_id("c016_00") == "016"
    assert normalize_unit_id("[016] Rapi: Red Hood") == "016"
    assert normalize_unit_id(16) == "016"
    with pytest.raises(ValueError):
        normalize_unit_id("no digits here")


def test_variant_suffix():
    assert variant_suffix("Rapi: Red Hood") == "Red Hood"
    assert variant_suffix("라피 : 레드 후드") == "레드 후드"
    assert variant_suffix("Modernia") is None


def test_index_resolves_every_language_to_one_unit():
    index = build_name_index(ROSTER)
    for spelling in ("Rapi: Red Hood", "라피 : 레드 후드", "ラピ：レッドフード", "rapi red hood"):
        assert index.resolve(spelling) == "016"
    assert index.resolve("Rapi") == "010"
    assert index.resolve("라피") == "010"


def test_variant_suffix_is_a_fallback_not_an_override():
    """`Red Hood` alone should reach 016 without shadowing the base unit."""
    index = build_name_index(ROSTER)
    assert index.resolve("Red Hood") == "016"
    assert index.resolve("레드 후드") == "016"
    assert index.resolve("Rapi") == "010"


def test_unknown_names_are_reported_not_guessed():
    index = build_name_index(ROSTER)
    resolved, unresolved = index.resolve_all(["Modernia", "Totally Not A Nikke"])
    assert resolved == {"Modernia": "260"}
    assert unresolved == ["Totally Not A Nikke"]


def test_colliding_names_raise_rather_than_silently_merging():
    index = NameIndex()
    index.add_primary("Rapi", "010")
    with pytest.raises(ValueError, match="collision"):
        index.add_primary("Rapi", "999")


def test_ambiguous_suffix_is_dropped():
    """Two units sharing a shorthand must resolve to neither, not to one at random."""
    roster = [
        {"unit_id": "100", "name_en": "A: Summer"},
        {"unit_id": "200", "name_en": "B: Summer"},
    ]
    index = build_name_index(roster)
    assert index.resolve("Summer") is None
    assert normalize_name("Summer") in index.ambiguous


def test_manual_alias_beats_auto_suffix():
    index = build_name_index(ROSTER, aliases=[{"unit_id": "260", "alias": "Red Hood"}])
    assert index.resolve("Red Hood") == "260"
