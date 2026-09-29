"""Incremental ranking collection against a fake GraphQL endpoint."""

import json

import pytest

from nikke_analysis.collect import enikk
from nikke_analysis.collect.base import CollectorError
from nikke_analysis.config import EnikkConfig
from nikke_analysis.util.http import Response
from nikke_analysis.util.snapshot import list_runs


class FakeGraphQL:
    """Answers the season list and per-season rankings; counts ranking requests."""

    def __init__(self, stamps, rankers=None, broken=()):
        self.stamps = stamps  # season -> lastupdated ("" = no rankings yet)
        self.rankers = rankers or {}  # season -> number of ranked players
        self.broken = set(broken)
        self.requested: list[int] = []

    def post_json(self, url, body, headers=None, allow_status=None):
        query = body["query"]
        if "soloRaidSummaries" in query:
            rows = [{"raid_number": s, "data": {"lastupdated": t} if t else None} for s, t in self.stamps.items()]
            payload = {"data": {"soloRaidSummaries": rows}}
        else:
            raid = int(body["variables"]["raid"])
            self.requested.append(raid)
            if raid in self.broken:
                payload = {"errors": [{"message": "boom"}]}
            else:
                count = self.rankers.get(raid, 3 if self.stamps.get(raid) else 0)
                payload = {"data": {"SRRankings": [{"rank": i + 1, "stamp": self.stamps.get(raid)} for i in range(count)]}}
        return Response(url, 200, json.dumps(payload).encode(), "application/json", {})


@pytest.fixture(autouse=True)
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("NIKKE_DATA_ROOT", str(tmp_path))


def collect(fake, **kwargs):
    return enikk.collect_rankings(config=EnikkConfig(delay=0), fetcher=fake, **kwargs)


def test_first_run_stores_every_played_season():
    fake = FakeGraphQL({1: "a", 2: "b", 3: ""})
    result = collect(fake)
    assert result["fetched"] == [1, 2]
    assert result["no_rankings_yet"] == [3]  # asked about, nothing stored
    [run] = list_runs(enikk.SOURCE)
    assert sorted(e["meta"]["raid"] for e in run.entries) == [1, 2]
    assert run.entries[0]["meta"]["rankers"] == 3


def test_unchanged_seasons_are_not_read_again():
    collect(FakeGraphQL({1: "a", 2: "b"}))
    again = FakeGraphQL({1: "a", 2: "b"})
    result = collect(again)
    assert again.requested == [] and result["snapshot_dir"] == ""
    assert len(list_runs(enikk.SOURCE)) == 1


def test_only_the_season_whose_stamp_moved_is_read():
    collect(FakeGraphQL({1: "a", 2: "b"}))
    live = FakeGraphQL({1: "a", 2: "c"})
    result = collect(live)
    assert live.requested == [2] and result["fetched"] == [2]


def test_forcing_a_season_rereads_it_but_identical_bytes_are_not_stored_twice():
    collect(FakeGraphQL({1: "a", 2: "b"}))
    forced = FakeGraphQL({1: "a", 2: "b"})
    result = collect(forced, seasons=[1])
    assert forced.requested == [1]
    assert result["unchanged"] == [1] and result["fetched"] == []


def test_one_failing_season_does_not_cost_the_others():
    fake = FakeGraphQL({1: "a", 2: "b"}, broken=[2])
    result = collect(fake)
    assert result["fetched"] == [1] and list(result["failed"]) == [2]
    retry = FakeGraphQL({1: "a", 2: "b"})
    assert collect(retry)["fetched"] == [2]  # nothing stored for 2, so it is asked again


def test_every_request_failing_is_an_error():
    with pytest.raises(CollectorError):
        collect(FakeGraphQL({1: "a"}, broken=[1]))
    assert list_runs(enikk.SOURCE) == []


class FakeImages:
    """Answers the image resizer: a WebP for every picture but those in ``bad``."""

    WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 "

    def __init__(self, bad=()):
        self.bad = set(bad)
        self.requested: list[str] = []

    def get(self, url, params=None, headers=None, allow_status=None):
        self.requested.append(url)
        if any(f"%2F{name}.png" in url for name in self.bad):
            return Response(url, 200, b"<html>", "text/html", {})
        return Response(url, 200, self.WEBP, "image/webp", {})


def test_boss_pictures_are_fetched_once(tmp_path):
    fake = FakeImages()
    result = enikk.collect_boss_images(["full_eba002_hsta", "full_bba001", "../etc"], directory=tmp_path, fetcher=fake)
    assert result["fetched"] == ["full_eba002_hsta", "full_bba001"]  # a name that is not a plain file name is skipped
    assert fake.requested[0].endswith("/_next/image?url=%2Fbosses%2Ffull_eba002_hsta.png&w=256&q=75")
    assert (tmp_path / "bosses" / "full_bba001.webp").read_bytes() == FakeImages.WEBP
    again = FakeImages()
    assert enikk.collect_boss_images(["full_eba002_hsta", "full_bba001"], directory=tmp_path, fetcher=again)["present"] == 2
    assert again.requested == []


def test_a_boss_picture_that_is_not_webp_is_an_error_after_the_others(tmp_path):
    fake = FakeImages(bad=["full_bba001"])
    with pytest.raises(CollectorError, match="full_bba001"):
        enikk.collect_boss_images(["full_bba001", "full_bbg003"], directory=tmp_path, fetcher=fake)
    assert not (tmp_path / "bosses" / "full_bba001.webp").exists()
    assert (tmp_path / "bosses" / "full_bbg003.webp").exists()
