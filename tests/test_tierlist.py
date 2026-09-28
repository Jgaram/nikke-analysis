"""Finding a unit by whatever a person types: an id, a name in either language,
an alias, or part of a name."""

import pandas as pd
import pytest

from nikke_analysis.tierlist import find_unit
from nikke_analysis.util.names import build_name_index

ROSTER = [
    {"unit_id": "016", "name_en": "Rapi: Red Hood", "name_ko": "라피 : 레드 후드"},
    {"unit_id": "330", "name_en": "Crown", "name_ko": "크라운"},
    {"unit_id": "351", "name_en": "Anchor: Innocent Maid", "name_ko": "앵커 : 이노센트 메이드"},
    {"unit_id": "352", "name_en": "Snow White: Innocent Days", "name_ko": "스노우 화이트 : 이노센트 데이즈"},
    {"unit_id": "392", "name_en": "Rei", "name_ko": "라이"},
    {"unit_id": "831", "name_en": "Rei", "name_ko": "레이"},
]
UNITS = pd.DataFrame(ROSTER)
INDEX = build_name_index(ROSTER, aliases=[{"unit_id": "016", "alias": "레드후드"}])


@pytest.mark.parametrize("query", ["330", "c330", "크라운", "crown", " Crown "])
def test_an_id_or_either_name_finds_the_unit(query):
    assert find_unit(query, UNITS, INDEX) == "330"


def test_aliases_and_spacing_do_not_matter():
    assert find_unit("레드후드", UNITS, INDEX) == "016"
    assert find_unit("라피 레드후드", UNITS, INDEX) == "016"
    assert find_unit("앵커", UNITS, INDEX) == "351"  # unique part of a name


def test_a_name_two_units_share_asks_for_the_id():
    with pytest.raises(LookupError, match="여러 니케의 이름"):
        find_unit("Rei", UNITS, INDEX)
    assert find_unit("라이", UNITS, INDEX) == "392"
    assert find_unit("831", UNITS, INDEX) == "831"


def test_a_part_that_fits_several_units_lists_them():
    with pytest.raises(LookupError, match="여러 니케와 맞는다") as found:
        find_unit("이노센트", UNITS, INDEX)
    assert "(351)" in str(found.value) and "(352)" in str(found.value)


def test_only_units_in_the_table_are_answered():
    released = UNITS[UNITS["unit_id"] != "330"]
    with pytest.raises(LookupError, match="없다"):
        find_unit("크라운", released, INDEX)
    with pytest.raises(LookupError):
        find_unit("330", released, INDEX)
    # a shared name is not ambiguous when only one of the two is there
    assert find_unit("Rei", UNITS[UNITS["unit_id"] != "831"], INDEX) == "392"


def test_it_works_without_an_alias_table():
    assert find_unit("크라운", UNITS) == "330"
    assert find_unit("라피 : 레드 후드", UNITS) == "016"
