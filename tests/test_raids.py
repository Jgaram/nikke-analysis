import pytest

from nikke_analysis.config import FieldMapping
from nikke_analysis.build.raids import _as_float, parse_document, resolve_path
from nikke_analysis.util.names import build_name_index

ROSTER = [
    {"unit_id": "010", "name_en": "Rapi", "name_ko": "라피"},
    {"unit_id": "016", "name_en": "Rapi: Red Hood", "name_ko": "라피 : 레드 후드"},
    {"unit_id": "260", "name_en": "Modernia", "name_ko": "모더니아"},
]

PAYLOAD = {
    "data": {
        "season": "40",
        "rankers": [
            {
                "rank": 1,
                "damage": "12,345,678",
                "nickname": "alpha",
                "boss": "Kraken",
                "team": [{"name": "Red Hood"}, {"name": "모더니아"}, {"name": "라피"}],
            },
            {
                "rank": 2,
                "damage": "11.5M",
                "nickname": "beta",
                "boss": "Kraken",
                "team": [{"name": "Modernia"}, {"name": "Who Even Is This"}],
            },
        ],
    }
}

MAPPING = FieldMapping(
    entries="data.rankers[]",
    rank="rank",
    score="damage",
    player="nickname",
    team="team[]",
    unit_name="name",
    boss="boss",
)


def test_resolve_path_flattens_marked_segments():
    assert resolve_path(PAYLOAD, "data.rankers[].rank") == [1, 2]
    assert resolve_path(PAYLOAD, "data.season") == ["40"]


def test_resolve_path_returns_empty_for_missing_keys():
    assert resolve_path(PAYLOAD, "data.nope[].x") == []
    assert resolve_path(PAYLOAD, "") == []


@pytest.mark.parametrize(
    "raw,expected",
    [("12,345,678", 12345678.0), ("11.5M", 11_500_000.0), ("2.4B", 2.4e9), (42, 42.0), ("", 0.0), (None, 0.0)],
)
def test_score_parsing_handles_site_formats(raw, expected):
    assert _as_float(raw) == expected


def test_parse_document_emits_one_row_per_slot():
    index = build_name_index(ROSTER)
    entries, unresolved = parse_document(PAYLOAD, MAPPING, index, season_default="40")
    assert [(e.rank, e.slot, e.unit_id) for e in entries] == [
        (1, 0, "016"),
        (1, 1, "260"),
        (1, 2, "010"),
        (2, 0, "260"),
    ]
    assert entries[0].score == 12345678.0
    assert entries[0].boss == "Kraken"
    assert entries[0].season == "40"


def test_unresolvable_names_are_reported_not_dropped_silently():
    index = build_name_index(ROSTER)
    _, unresolved = parse_document(PAYLOAD, MAPPING, index)
    assert unresolved == ["Who Even Is This"]


def test_explicit_unit_ids_bypass_name_resolution():
    payload = {"rows": [{"rank": 3, "team": [{"cid": "c016_00"}, {"cid": 260}]}]}
    mapping = FieldMapping(entries="rows[]", rank="rank", team="team[]", unit_id="cid")
    entries, unresolved = parse_document(payload, mapping, build_name_index(ROSTER))
    assert [e.unit_id for e in entries] == ["016", "260"]
    assert unresolved == []


def test_rank_falls_back_to_list_position():
    payload = {"rows": [{"team": [{"name": "Rapi"}]}, {"team": [{"name": "Modernia"}]}]}
    mapping = FieldMapping(entries="rows[]", team="team[]", unit_name="name")
    entries, _ = parse_document(payload, mapping, build_name_index(ROSTER))
    assert [e.rank for e in entries] == [1, 2]
