"""Server names and choosing some of them: --server, --exclude, tiers.yaml."""

import pandas as pd
import pytest

from nikke_analysis.analyze import metrics, tiers
from nikke_analysis.cli import _servers, build_parser
from nikke_analysis.servers import SERVERS, ServerError, ServerFilter, describe, normalize, ordered, split


@pytest.mark.parametrize(
    "name, expected",
    [
        ("KR", "KR"), ("kr", "KR"), (" Kr ", "KR"), ("한국", "KR"), ("한섭", "KR"),
        ("global", "GLOBAL"), ("글로벌", "GLOBAL"),
        ("일본", "JP"), ("north america", "NA"), ("북미", "NA"), ("na", "NA"),
        ("동남아", "SEA"), ("sea", "SEA"),
        ("TW-HK", "TW-HK"), ("tw-hk", "TW-HK"), ("tw/hk", "TW-HK"), ("TWHK", "TW-HK"), ("tw", "TW-HK"),
        ("대만", "TW-HK"), ("대만·홍콩", "TW-HK"),
    ],
)
def test_any_spelling_of_a_server_reads_as_enikks(name, expected):
    assert normalize(name) == expected


def test_an_unknown_name_is_kept_for_the_data_to_judge():
    assert normalize("eu") == "EU" and normalize("s1") == "S1"


def test_names_come_repeated_or_comma_separated_without_duplicates():
    assert split(["kr,jp", "KR", " sea "]) == ("KR", "JP", "SEA")
    assert split("한국, 일본") == ("KR", "JP")
    assert split(None) == () and split([]) == () and split(["", " , "]) == ()


def test_known_servers_sort_in_their_usual_order():
    assert ordered(["TW-HK", "EU", "KR", "GLOBAL", "KR"]) == ["GLOBAL", "KR", "TW-HK", "EU"]


def test_include_minus_exclude():
    assert ServerFilter().keep(SERVERS) == list(SERVERS) and not ServerFilter()
    assert ServerFilter.of("kr,jp").keep(SERVERS) == ["JP", "KR"]
    assert ServerFilter.of(exclude="na,sea").keep(SERVERS) == ["GLOBAL", "JP", "KR", "TW-HK"]
    assert ServerFilter.of("kr,jp,na", "na").keep(SERVERS) == ["JP", "KR"]


def test_a_name_the_data_does_not_have_is_an_error_not_a_no_op():
    with pytest.raises(ServerError, match="없는 서버: XX"):
        ServerFilter.of(exclude="xx").check(SERVERS)
    with pytest.raises(ServerError, match="하나도 남지 않는다"):
        ServerFilter.of("kr", "한국").check(SERVERS)
    assert ServerFilter.of(exclude="kr").check(["KR", "JP"]) == ["JP"]
    assert isinstance(ServerError("x"), LookupError)  # the CLI reports LookupError as a message


def test_labels_say_what_was_chosen():
    both = ServerFilter.of("kr,jp,na", "na")
    assert (ServerFilter.of("kr,jp").label, ServerFilter.of(exclude="na,sea").label, both.label) == (
        "KR·JP", "NA·SEA 제외", "KR·JP·NA 중 NA 제외")
    assert ServerFilter.of(exclude="na").caption == "NA 제외 전 서버" and both.caption == "KR·JP·NA 중 NA 제외"
    assert ServerFilter.of("kr").caption == "KR 서버만" and ServerFilter().caption == ""
    assert (ServerFilter.of("kr,jp").slug, ServerFilter.of(exclude="na,tw").slug, both.slug, ServerFilter().slug) == (
        "KR+JP", "excl-NA+TW-HK", "KR+JP+NA_excl-NA", "all")
    assert describe(ServerFilter(), SERVERS) == "6개 서버"
    assert describe(ServerFilter.of(exclude="na"), ["GLOBAL", "JP", "KR", "SEA", "TW-HK"]) == "NA 제외 5개 서버"
    assert describe(ServerFilter.of("kr"), ["KR"]) == "KR"


def test_population_keeps_the_chosen_servers():
    entries = pd.DataFrame({"server": ["KR", "JP", "NA", "KR"], "rank": [1, 1, 1, 60], "deck_score": [1, 1, 1, 1]})
    assert list(metrics.select_population(entries)["server"]) == ["KR", "JP", "NA"]
    assert list(metrics.select_population(entries, servers=("KR", "NA"))["server"]) == ["KR", "NA"]
    assert list(metrics.select_population(entries, exclude=("NA",))["server"]) == ["KR", "JP"]
    assert list(metrics.select_population(entries, servers=("KR", "NA"), exclude=("NA",))["server"]) == ["KR"]


def test_the_config_takes_an_exclusion_list_in_any_spelling(tmp_path):
    path = tmp_path / "tiers.yaml"
    path.write_text("population: {servers: [kr, 일본], exclude_servers: [tw]}\n", encoding="utf-8")
    config = tiers.load_tier_config(path)
    assert (config.servers, config.exclude_servers) == (("KR", "JP"), ("TW-HK",))
    assert config.server_filter == ServerFilter(("KR", "JP"), ("TW-HK",))


def test_a_command_line_choice_replaces_the_configured_one():
    config = tiers.TierConfig(servers=("KR",), exclude_servers=("JP",), half_life_days=90)
    other = config.with_servers(ServerFilter.of(exclude="na"))
    assert (other.servers, other.exclude_servers, other.half_life_days) == ((), ("NA",), 90)
    assert config.servers == ("KR",)  # the original is left as it was


def test_the_repo_config_pools_every_server():
    assert not tiers.load_tier_config().server_filter


@pytest.mark.parametrize("command", [["tier"], ["tier", "--unit", "크라운"], ["raid", "40"], ["analyze"], ["viz"]])
def test_every_view_takes_server_and_exclude(command):
    args = build_parser().parse_args([*command, "--server", "kr,jp", "--server", "한국", "--exclude", "jp"])
    assert _servers(args) == ServerFilter(("KR", "JP"), ("JP",))
    assert not _servers(build_parser().parse_args(command))
