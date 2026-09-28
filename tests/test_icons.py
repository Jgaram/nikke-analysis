"""Icons: where they come from, how they are kept, and what a chart does without one.

No network: the CDN path rule is checked against URLs the live CDN answered,
and the collector runs against a fake fetcher.
"""

import csv
import io

import pandas as pd
import pytest
from PIL import Image

from nikke_analysis import health
from nikke_analysis.analyze import pipeline
from nikke_analysis.collect import blablalink
from nikke_analysis.collect.base import CollectorError
from nikke_analysis.paths import attribute_icon_path, burst_icon_path, class_icon_path, element_icon_path, unit_icon_path
from nikke_analysis.util.http import Response
from nikke_analysis.viz import charts
from tests.synthetic import make_world, write_processed


def image_bytes(fmt: str, size=(8, 8), color=(200, 40, 40, 255)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", size, color).save(buffer, format=fmt)
    return buffer.getvalue()


WEBP = image_bytes("WEBP")
PNG = image_bytes("PNG")


class FakeFetcher:
    """Answers by URL; anything not listed is a 404, like the CDN."""

    def __init__(self, answers: dict[str, tuple[int, bytes]]):
        self.answers = answers
        self.calls: list[str] = []

    def get(self, url, *, allow_status=None, **_):
        self.calls.append(url)
        status, body = self.answers.get(url, (404, b"<Error>NoSuchKey</Error>"))
        if status >= 400 and status not in (allow_status or ()):
            raise RuntimeError(f"GET {url} -> HTTP {status}")
        return Response(url, status, body, "image/webp" if body[:4] == b"RIFF" else "text/html", {})


def site_answers(body: bytes = PNG) -> dict[str, tuple[int, bytes]]:
    names = [name for _, files in blablalink.ATTRIBUTE_ICONS.values() for name in files.values()]
    return {blablalink.site_image_url(name): (200, body) for name in names}


ATTRIBUTE_ICON_COUNT = sum(len(files) for _, files in blablalink.ATTRIBUTE_ICONS.values())


# --------------------------------------------------------------------------
# the CDN path rule
# --------------------------------------------------------------------------

def test_cdn_paths_follow_the_site_rule():
    # Both answered 200 from sg-tools-cdn.blablalink.com; the first is also the
    # portrait URL nikke-calc's scraper derives for Rapi.
    assert blablalink.obfuscate("/character/mi/mi_c010_00_s.webp") == "ds-16/yt-22/67e341816e80e0c1e13903e5de58875b.webp"
    assert blablalink.unit_icon_url("010") == (
        "https://sg-tools-cdn.blablalink.com/gn-03/nj-68/48bc957318d19b4d873a9b423d6d51fa.webp")
    assert blablalink.unit_icon_url("10") == blablalink.unit_icon_url("010")


def test_only_png_and_webp_count_as_images():
    assert blablalink.is_image(PNG) and blablalink.is_image(WEBP)
    assert not blablalink.is_image(b"<!doctype html><html>")
    assert not blablalink.is_image(b"")


# --------------------------------------------------------------------------
# collection
# --------------------------------------------------------------------------

def test_collection_fetches_what_is_missing_and_skips_units_not_on_the_cdn(tmp_path):
    answers = site_answers() | {blablalink.unit_icon_url("010"): (200, WEBP)}
    fetcher = FakeFetcher(answers)

    result = blablalink.collect_icons(["010", "999"], directory=tmp_path, fetcher=fetcher)

    assert unit_icon_path("010", tmp_path).read_bytes() == WEBP
    assert not unit_icon_path("999", tmp_path).exists()
    assert result.not_yet == ["999"]
    assert element_icon_path("Electric", tmp_path).read_bytes() == PNG
    assert class_icon_path("Supporter", tmp_path).is_file()
    assert burst_icon_path("I-II-III", tmp_path).is_file()
    assert attribute_icon_path("manufacturers", "Tetra Line", tmp_path).name == "tetra-line.png"
    assert attribute_icon_path("manufacturers", "Tetra Line", tmp_path).is_file()
    assert attribute_icon_path("weapons", "Sub Machine Gun", tmp_path).is_file()
    assert "010" in result.fetched and result.present == 0

    # Next run: only the unit still missing is asked for.
    again = FakeFetcher(answers)
    result = blablalink.collect_icons(["010", "999"], directory=tmp_path, fetcher=again)
    assert again.calls == [blablalink.unit_icon_url("999")]
    assert result.fetched == [] and result.present == ATTRIBUTE_ICON_COUNT + 1


def test_collection_reads_the_roster_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("NIKKE_DATA_ROOT", str(tmp_path))
    processed = tmp_path / "processed"
    processed.mkdir()
    (processed / "roster.csv").write_text("unit_id,name_ko\n010,라피\n011,네온\n", encoding="utf-8")
    fetcher = FakeFetcher(site_answers())
    result = blablalink.collect_icons(fetcher=fetcher)
    assert result.not_yet == ["010", "011"]
    assert result.directory == str(tmp_path / "assets" / "icons")


def test_a_page_instead_of_an_image_fails_after_the_rest_are_saved(tmp_path):
    """The site answers any unknown asset path with its HTML shell and a 200.

    That must not be saved as an icon, and it must not pass quietly either: it
    means the site moved its assets.
    """
    answers = site_answers() | {blablalink.site_image_url("icon-code-fire.png"): (200, b"<!doctype html>")}
    answers[blablalink.unit_icon_url("010")] = (200, WEBP)
    with pytest.raises(CollectorError, match="elements:Fire"):
        blablalink.collect_icons(["010"], directory=tmp_path, fetcher=FakeFetcher(answers))
    assert not element_icon_path("Fire", tmp_path).exists()
    assert unit_icon_path("010", tmp_path).is_file()
    assert element_icon_path("Water", tmp_path).is_file()


def test_a_missing_attribute_icon_is_a_failure_not_a_unit_to_wait_for(tmp_path):
    answers = site_answers()
    del answers[blablalink.site_image_url("icon-burst-p.png")]
    with pytest.raises(CollectorError, match="bursts:I-II-III"):
        blablalink.collect_icons([], directory=tmp_path, fetcher=FakeFetcher(answers))


# --------------------------------------------------------------------------
# charts
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def processed(tmp_path_factory):
    directory = tmp_path_factory.mktemp("processed")
    world = make_world(seasons=6, rankers=10, fillers=12, seed=3)
    write_processed(world, directory)
    pipeline.run(data_dir=directory)
    return directory


def shown_units(directory) -> set[str]:
    frame = pd.read_csv(directory / "metrics_unit_season.csv", dtype={"unit_id": str})
    return set(frame["unit_id"])


def write_icons(directory, unit_ids) -> None:
    for unit_id in unit_ids:
        path = unit_icon_path(unit_id, directory)
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (128, 128), (90, 140, 200, 255)).save(path, format="WEBP")
    for kind, (_, files) in blablalink.ATTRIBUTE_ICONS.items():
        for value in files:
            path = attribute_icon_path(kind, value, directory)
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGBA", (17, 37), (255, 255, 255, 255)).save(path)


def test_charts_draw_faces_instead_of_names(processed, tmp_path):
    icons = tmp_path / "icons"
    write_icons(icons, shown_units(processed))
    result = charts.render_all(data_dir=processed, out_dir=tmp_path / "out", icons_dir=icons)
    assert len(result["written"]) == 14
    assert result["named_units"] == []


def test_charts_fall_back_to_names_without_icons(processed, tmp_path):
    """No icon on disk is never a broken chart: the unit is drawn by name."""
    icons = tmp_path / "icons"
    missing = sorted(shown_units(processed))[:2]
    write_icons(icons, shown_units(processed) - set(missing))
    (element_icon_path("Fire", icons)).unlink()
    result = charts.render_all(data_dir=processed, out_dir=tmp_path / "out", themes=("dark",), icons_dir=icons)
    assert len(result["written"]) == 7
    assert set(result["named_units"]) <= set(missing) and result["named_units"]

    bare = charts.render_all(data_dir=processed, out_dir=tmp_path / "bare", themes=("light",),
                             icons_dir=tmp_path / "none")
    assert len(bare["written"]) == 7
    assert bare["named_units"]


# --------------------------------------------------------------------------
# health
# --------------------------------------------------------------------------

def test_a_ranked_unit_without_a_face_is_a_warning(tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir()
    with (processed / "metrics_element_tiers.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["unit_id", "name_ko", "name_en"])
        writer.writeheader()
        writer.writerows([{"unit_id": "010", "name_ko": "라피", "name_en": "Rapi"},
                          {"unit_id": "872", "name_ko": "신캐", "name_en": ""}])
    icons = tmp_path / "icons"
    write_icons(icons, ["010"])

    issues = health.icon_issues(processed, icons)
    assert [(i.level, i.code, i.subject) for i in issues] == [("warning", "unit_icon_missing", "신캐")]
    assert not health.has_errors(issues)

    element_icon_path("Wind", icons).unlink()
    assert ("icon_missing", "elements/Wind") in {(i.code, i.subject) for i in health.icon_issues(processed, icons)}


def test_a_roster_value_without_an_icon_mapping_is_a_warning(tmp_path):
    """A new weapon type must not go unnoticed just because no chart draws it yet."""
    processed = tmp_path / "processed"
    processed.mkdir()
    (processed / "roster.csv").write_text(
        "unit_id,element,unit_class,burst,manufacturer,weapon\n"
        "010,Fire,Attacker,II,Elysion,Assault Rifle\n"
        "999,Fire,Attacker,II,Elysion,Laser Cannon\n", encoding="utf-8")
    icons = tmp_path / "icons"
    write_icons(icons, [])
    issues = health.icon_issues(processed, icons)
    assert [(i.code, i.subject) for i in issues] == [("icon_unmapped", "weapons/Laser Cannon")]


def test_burst_glyphs_share_one_width(tmp_path):
    """I is narrow and III wide; padded to one width, every row label lines up."""
    from matplotlib.colors import to_rgb

    from nikke_analysis.viz import theme as th
    from nikke_analysis.viz.icons import BURST_CANVAS, Icons

    for burst, width in (("I", 17), ("III", 40)):
        path = burst_icon_path(burst, tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (width, 37), (255, 255, 255, 255)).save(path)
    icons = Icons(th.LIGHT, tmp_path)
    narrow, wide = icons.burst("I"), icons.burst("III")
    assert narrow.shape == wide.shape == (37, BURST_CANVAS, 4)
    # Tinted to the theme's ink, not left white on a pale surface.
    assert tuple(narrow[18, BURST_CANVAS // 2, :3].round(3)) == tuple(round(c, 3) for c in to_rgb(th.LIGHT.ink_secondary))
    assert icons.burst("II") is None
