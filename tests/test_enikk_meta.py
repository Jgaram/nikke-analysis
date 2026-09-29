from nikke_analysis.build.enikk_meta import normalize_character
from nikke_analysis.util.nextjs import find_objects, flight_payload


def test_characters_are_read_out_of_the_rsc_payload():
    record = '{"id":140401,"name_localkey":"Guilty: Mighty Bunny","resource_id":404,"class":"Attacker","element_id":{"element":"Water"}}'
    escaped = record.replace('"', '\\"')
    html = f'<script>self.__next_f.push([1,"12:[\\"$\\",\\"div\\",null,{{\\"c\\":[{escaped}]}}]"])</script>'
    [found] = find_objects(flight_payload(html), ("resource_id", "name_localkey"))
    assert found["resource_id"] == 404


def test_enikk_vocabulary_maps_onto_the_roster():
    unit = normalize_character(
        {
            "resource_id": 470,
            "name_localkey": "Red Hood",
            "original_rare": "SSR",
            "use_burst_skill": "AllStep",
            "element_id": {"element": "Electronic"},
            "corporation": "PILGRIM",
            "class": "Attacker",
            "weapon": "SR",
            "squadInfo": {"name": "Goddess"},
        }
    )
    assert unit == {
        "unit_id": "470",
        "name_en": "Red Hood",
        "rarity": "SSR",
        "burst": "I-II-III",
        "element": "Electric",
        "manufacturer": "Pilgrim",
        "unit_class": "Attacker",
        "weapon": "Sniper Rifle",
        "squad": "Goddess",
        "first_seen": "",
    }


def test_a_boss_picture_name_must_be_a_plain_file_name():
    from nikke_analysis.build.enikk_meta import boss_image

    assert boss_image("full_eba002_hsta") == "full_eba002_hsta"
    assert boss_image("../x") == "" and boss_image(None) == "" and boss_image("a b") == ""
