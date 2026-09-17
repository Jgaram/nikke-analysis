import json

from nikke_analysis.build import patches
from nikke_analysis.util.names import build_name_index

ROSTER = [
    {"unit_id": "010", "name_en": "Rapi", "name_ko": "라피"},
    {"unit_id": "016", "name_en": "Rapi: Red Hood", "name_ko": "라피 : 레드 후드"},
    {"unit_id": "260", "name_en": "Modernia", "name_ko": "모더니아"},
]


def announcement(patch_id, date_ts, title, body):
    return {
        "patch_id": patch_id,
        "timestamp": date_ts,
        "date": __import__("datetime").datetime.utcfromtimestamp(date_ts).date().isoformat(),
        "title": title,
        "url": "",
        "source": "steam",
        "body": body,
    }


def test_clean_body_strips_html_and_bbcode():
    raw = "<h1>Update</h1>[b]New Nikke[/b]<br>&amp; more"
    cleaned = patches.clean_body(raw)
    assert "<" not in cleaned and "[b]" not in cleaned
    assert "New Nikke" in cleaned and "&" in cleaned


def test_classify_recognises_korean_and_english_wording():
    assert patches.classify("Maintenance Notice", "") == "maintenance"
    assert patches.classify("정기 점검 안내", "") == "maintenance"
    assert patches.classify("업데이트 안내", "") == "patchnote"
    assert patches.classify("Random blog post", "nothing here") == "other"


def test_section_titles_skip_prose():
    body = "Pick Up Recruit\nThis is a full sentence that should be ignored.\n이벤트 안내"
    titles = patches.section_titles(body)
    assert "Pick Up Recruit" in titles
    assert "이벤트 안내" in titles
    assert not any(t.endswith(".") for t in titles)


def test_find_units_prefers_the_longest_matching_alias():
    index = build_name_index(ROSTER)
    pairs = patches._alias_lookup(index)
    found = patches.find_units("New Nikke: Rapi: Red Hood joins the squad", pairs)
    assert found.get("016")
    # `Rapi` also appears as a substring, and that is fine - both are named -
    # but the variant must not be missed in favour of the base unit.
    assert "016" in found


def test_first_announcement_with_new_unit_wording_wins():
    index = build_name_index(ROSTER)
    records = [
        announcement("a", 1_700_000_000, "Weekly notice", "Modernia is mentioned in passing"),
        announcement("b", 1_700_500_000, "New Nikke: Modernia", "Pick Up recruitment opens"),
    ]
    releases, stats = patches.extract_releases(records, index)
    by_unit = {r.unit_id: r for r in releases}
    assert by_unit["260"].patch_id == "b"
    assert by_unit["260"].status == "confirmed"
    assert stats["confirmed"] == 1


def test_a_passing_mention_alone_stays_a_candidate():
    index = build_name_index(ROSTER)
    records = [announcement("a", 1_700_000_000, "Weekly notice", "Rapi appears in the story")]
    releases, _ = patches.extract_releases(records, index)
    assert releases[0].status == "candidate"


def test_parse_steam_run_flattens_pages(tmp_path):
    from nikke_analysis.util.snapshot import SnapshotWriter, list_runs

    payload = {
        "appnews": {
            "newsitems": [
                {"gid": "1", "title": "New Nikke", "contents": "[b]Pick Up[/b]", "date": 1_700_000_000, "url": "u"}
            ]
        }
    }
    writer = SnapshotWriter("patchnotes_steam", root=tmp_path)
    writer.write("news-000.json", json.dumps(payload).encode(), url="x")
    writer.seal()

    run = list_runs("patchnotes_steam", root=tmp_path)[0]
    records = patches.parse_steam_run(run)
    assert len(records) == 1
    assert records[0]["title"] == "New Nikke"
    assert records[0]["date"] == "2023-11-14"
    assert "[b]" not in records[0]["body"]
