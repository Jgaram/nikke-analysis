import json

import pytest

from nikke_analysis.build import raids
from nikke_analysis.build.raids import UnitFacts, UnitResolver, _as_float, parse_document
from nikke_analysis.config import RankingMapping
from nikke_analysis.util.jsonpath import resolve_one, resolve_path
from nikke_analysis.util.names import build_name_index
from nikke_analysis.util.snapshot import SnapshotWriter

ROSTER = [
    {"unit_id": "010", "name_en": "Rapi", "name_ko": "라피"},
    {"unit_id": "016", "name_en": "Rapi: Red Hood", "name_ko": "라피 : 레드 후드"},
    {"unit_id": "260", "name_en": "Modernia", "name_ko": "모더니아"},
    {"unit_id": "330", "name_en": "Crown", "name_ko": "크라운"},
    {"unit_id": "082", "name_en": "Liter", "name_ko": "리타"},
    {"unit_id": "392", "name_en": "Rei", "name_ko": "라이"},
    {"unit_id": "831", "name_en": "Rei", "name_ko": "레이"},
]
FACTS = {
    "010": UnitFacts("2022-11-04", "Fire", "II"),
    "016": UnitFacts("2025-01-01", "Fire", "III"),
    "260": UnitFacts("2023-01-01", "Fire", "III"),
    "330": UnitFacts("2024-04-25", "Iron", "II"),
    "082": UnitFacts("2022-11-04", "Iron", "I"),
    "392": UnitFacts("2023-04-27", "Water", "I"),
    "831": UnitFacts("2024-08-29", "Fire", "III"),
}
SEASONS = {
    6: {"start": "2023-10-12", "weak": "Wind"},
    22: {"start": "2025-02-06", "weak": "Water"},
    25: {"start": "2025-05-08", "weak": "Fire"},
    31: {"start": "2025-11-13", "weak": "Wind"},
}


@pytest.fixture()
def resolver():
    return UnitResolver(build_name_index(ROSTER), FACTS, SEASONS)


def deck(damage, names, cp=None, cores=None):
    return {"damage": damage, "characters": names, "cpc": cp or [100000] * len(names), "cores": cores or [10] * len(names)}


def ranker(rank, player, server, decks):
    return {"rank": rank, "playerid": player, "server": server, "damage": sum(d["damage"] for d in decks),
            "collectionTime": "2025-05-14", "teams": decks}


def document(*rankers):
    return {"data": {"SRRankings": list(rankers)}}


def test_resolve_path_flattens_marked_segments():
    payload = document(ranker(1, "a", "KR", [deck(5, ["Crown"])]), ranker(2, "b", "JP", [deck(4, ["Liter"])]))
    assert resolve_path(payload, "data.SRRankings[].rank") == [1, 2]
    assert resolve_path(payload, "data.SRRankings[].teams[].damage") == [5, 4]
    assert resolve_one(payload, "data.SRRankings[].teams[].characters") == ["Crown"]
    assert resolve_path(payload, "data.nope[].x") == []
    assert resolve_path(payload, "") == []


@pytest.mark.parametrize(
    "raw,expected",
    [("12,345,678", 12345678.0), ("11.5M", 11_500_000.0), ("2.4B", 2.4e9), (42, 42.0), ("", 0.0), (None, 0.0)],
)
def test_score_parsing_handles_site_formats(raw, expected):
    assert _as_float(raw) == expected


def test_one_row_per_slot_with_the_deck_it_sat_in(resolver):
    payload = document(ranker(3, "p1", "KR", [
        deck(900, ["Rapi: Red Hood", "Crown", "Liter", "Modernia", "Rapi"], cp=[1, 2, 3, 4, 5], cores=[10, 9, 8, 7, 6]),
        deck(100, ["Rapi", "Crown"]),
    ]))
    entries, unresolved = parse_document(payload, RankingMapping(), resolver, season=25)
    assert unresolved == []
    assert [(e.deck, e.slot, e.unit_id) for e in entries[:5]] == [(1, 0, "016"), (1, 1, "330"), (1, 2, "082"), (1, 3, "260"), (1, 4, "010")]
    first = entries[0]
    assert (first.season, first.server, first.rank, first.player) == (25, "KR", 3, "p1")
    assert first.score == 1000 and first.deck_score == 900
    assert first.unit_cp == 1 and first.unit_cores == 10 and first.collected_at == "2025-05-14"
    assert [e.deck for e in entries[5:]] == [2, 2]


def test_players_outside_the_ranking_are_left_out(resolver):
    payload = document({**ranker(0, "x", "KR", [deck(1, ["Crown"])]), "rank": None}, ranker(1, "y", "KR", [deck(1, ["Crown"])]))
    entries, _ = parse_document(payload, RankingMapping(), resolver, season=25)
    assert {e.player for e in entries} == {"y"}


def test_unresolvable_names_are_reported_not_dropped_silently(resolver):
    payload = document(ranker(1, "p", "KR", [deck(10, ["Crown", "Who Even Is This"])]))
    entries, unresolved = parse_document(payload, RankingMapping(), resolver, season=25)
    assert [e.unit_id for e in entries] == ["330"]
    assert unresolved == [("Who Even Is This", "")]


def test_a_shared_name_is_settled_by_release_date(resolver):
    """Before 2024-08-29 only 라이 existed."""
    payload = document(ranker(1, "p", "KR", [deck(10, ["Rei", "Crown"])]))
    entries, unresolved = parse_document(payload, RankingMapping(), resolver, season=6)
    assert [e.unit_id for e in entries] == ["392", "330"] and unresolved == []


def test_a_shared_name_is_settled_by_the_burst_stage_the_deck_lacks(resolver):
    """Crown (II) and Liter (I) are there; the deck needs a III: 레이."""
    payload = document(ranker(1, "p", "KR", [deck(10, ["Liter", "Crown", "Rei"])]))
    entries, unresolved = parse_document(payload, RankingMapping(), resolver, season=31)
    assert [e.unit_id for e in entries] == ["082", "330", "831"] and unresolved == []


def test_a_shared_name_is_settled_by_the_boss_weakness(resolver):
    """Every stage is covered, so the element the boss is weak to decides."""
    names = ["Liter", "Crown", "Modernia", "Rei"]
    water, _ = parse_document(document(ranker(1, "p", "KR", [deck(10, names)])), RankingMapping(), resolver, season=22)
    fire, _ = parse_document(document(ranker(1, "p", "KR", [deck(10, names)])), RankingMapping(), resolver, season=25)
    assert water[-1].unit_id == "392" and fire[-1].unit_id == "831"


def test_a_shared_name_context_cannot_settle_is_reported(resolver):
    names = ["Liter", "Crown", "Modernia", "Rei"]
    entries, unresolved = parse_document(document(ranker(1, "p", "KR", [deck(10, names)])), RankingMapping(), resolver, season=31)
    assert [e.unit_id for e in entries] == ["082", "330", "260"]
    assert unresolved == [("Rei", "392;831")]


def test_build_reads_the_newest_snapshot_of_each_season(tmp_path, resolver):
    for players in (["old"], ["new-1", "new-2"]):
        writer = SnapshotWriter(raids.SOURCE, root=tmp_path)
        payload = document(*[ranker(i + 1, p, "KR", [deck(10, ["Crown"])]) for i, p in enumerate(players)])
        writer.write("season-025.json", json.dumps(payload).encode(), url="u",
                     meta={"kind": "rankings", "raid": 25, "lastupdated": players[0]})
        writer.seal()
    out = tmp_path / "processed"
    summary = raids.build(mapping=RankingMapping(), out_dir=out, resolver=resolver, snapshot_root=tmp_path)
    assert summary["rankers"] == 2 and summary["seasons"] == 1
    text = (out / raids.ENTRIES_CSV).read_text(encoding="utf-8")
    assert "new-1" in text and "old" not in text
    assert (out / raids.UNRESOLVED_CSV).is_file()
