import pytest

from nikke_analysis.build.jsobj import JsLiteralError, extract_array_literal, parse_js_literal


def test_parses_unquoted_keys_and_mixed_quotes():
    value = parse_js_literal("""{ id: 1, name: 'Rapi', tag: "SR", ok: true, none: null }""")
    assert value == {"id": 1, "name": "Rapi", "tag": "SR", "ok": True, "none": None}


def test_parses_numeric_keys_and_nesting():
    value = parse_js_literal("""{ specialties: { 1: "Buffer", 2: "Healer" }, cd: { "II": 20 } }""")
    assert value["specialties"] == {"1": "Buffer", "2": "Healer"}
    assert value["cd"] == {"II": 20}


def test_tolerates_trailing_commas_and_comments():
    source = """
    // leading comment
    const characters = [
        { id: 1, name: "A" },  /* inline */
        { id: 2, name: "B" },
    ];
    """
    rows = extract_array_literal(source, "characters")
    assert [r["name"] for r in rows] == ["A", "B"]


def test_escapes_and_unicode():
    assert parse_js_literal(r'{ s: "line\nbreak é" }')["s"] == "line\nbreak é"


def test_missing_variable_fails_loudly():
    with pytest.raises(JsLiteralError, match="no array assignment"):
        extract_array_literal("const other = [];", "characters")


def test_truncated_input_fails_loudly():
    with pytest.raises(JsLiteralError):
        parse_js_literal('{ a: "unterminated')
