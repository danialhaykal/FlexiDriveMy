"""QA audit C4: chart_svg is client-supplied markup embedded verbatim
(unescaped) into the exported PDF's HTML. These tests prove the specific
attacks the audit named are actually closed: reading server files via
file://, SSRF against internal URLs, hiding the legal disclaimer via
injected CSS, and breaking out of the template's chart <div> with
malformed/non-SVG text.
"""

import re
from pathlib import Path

import pytest

from apps.exports import svg_sanitizer
from apps.exports.svg_sanitizer import FALLBACK_PAINT, sanitize_chart_svg

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_blank_input_returns_blank():
    assert sanitize_chart_svg("") == ""
    assert sanitize_chart_svg("   ") == ""


def test_a_simple_safe_chart_survives_with_its_structure_and_attributes_intact():
    svg = '<svg viewBox="0 0 100 50"><rect x="0" y="0" width="20" height="40" fill="#2563eb" /></svg>'

    result = sanitize_chart_svg(svg)

    assert "<svg" in result
    assert "<rect" in result
    assert 'width="20"' in result
    assert 'height="40"' in result
    assert 'fill="#2563eb"' in result
    # viewBox is case-sensitive in real SVG - must survive with its real casing.
    assert "viewBox" in result


def test_gradients_and_clip_paths_keep_their_real_casing():
    svg = (
        '<svg><defs><linearGradient id="g1"><stop offset="0" stop-color="#fff" /></linearGradient>'
        '<clipPath id="c1"><rect x="0" y="0" width="10" height="10" /></clipPath></defs></svg>'
    )

    result = sanitize_chart_svg(svg)

    assert "<linearGradient" in result
    assert "<clipPath" in result
    assert "<stop" in result


# --- C4 attack vectors must all be neutralized -----------------------------


def test_script_element_is_dropped():
    svg = '<svg><script>alert(document.cookie)</script><circle cx="1" cy="1" r="1"/></svg>'
    result = sanitize_chart_svg(svg)
    assert "script" not in result.lower()
    assert "alert" not in result


def test_style_element_is_dropped_entirely():
    """A <style> tag inside the embedded SVG is not scoped to the SVG
    subtree once inserted raw into the page - it's a page-wide stylesheet
    that could hide the disclaimer (e.g. `.disclaimer{display:none}`)."""
    svg = '<svg><style>.disclaimer{display:none}</style><circle cx="1" cy="1" r="1"/></svg>'
    result = sanitize_chart_svg(svg)
    assert "style" not in result.lower()
    assert "display:none" not in result


def test_style_attribute_is_stripped_from_every_element():
    svg = '<svg><rect style="display:none" x="0" y="0" width="1" height="1"/></svg>'
    result = sanitize_chart_svg(svg)
    assert "style=" not in result


def test_class_attribute_is_stripped():
    svg = '<svg><rect class="disclaimer" x="0" y="0" width="1" height="1"/></svg>'
    result = sanitize_chart_svg(svg)
    assert "class=" not in result


def test_image_element_with_file_href_is_dropped():
    svg = '<svg><image href="file:///app/.env" /><circle cx="1" cy="1" r="1"/></svg>'
    result = sanitize_chart_svg(svg)
    assert "image" not in result.lower()
    assert "file://" not in result
    assert "<circle" in result  # the rest of the chart survives


def test_use_element_with_external_href_is_dropped():
    svg = '<svg><use href="http://internal.example/secret" /></svg>'
    result = sanitize_chart_svg(svg)
    assert "use" not in result.lower()
    assert "internal.example" not in result


def test_xlink_href_attribute_is_stripped_regardless_of_namespace_prefix():
    svg = (
        '<svg xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<a xlink:href="http://169.254.169.254/latest/meta-data/"><circle cx="1" cy="1" r="1"/></a></svg>'
    )
    result = sanitize_chart_svg(svg)
    assert "href" not in result.lower()
    assert "169.254.169.254" not in result
    assert "<a " not in result and "<a>" not in result  # <a> itself isn't allowlisted either


def test_foreign_object_and_iframe_are_dropped():
    svg = '<svg><foreignObject><iframe src="http://internal.example"></iframe></foreignObject></svg>'
    result = sanitize_chart_svg(svg)
    assert "foreignobject" not in result.lower()
    assert "iframe" not in result.lower()
    assert "internal.example" not in result


def test_on_event_handler_attributes_are_stripped():
    svg = '<svg><rect onclick="alert(1)" onload="alert(1)" x="0" y="0" width="1" height="1"/></svg>'
    result = sanitize_chart_svg(svg)
    assert "onclick" not in result
    assert "onload" not in result


def test_malformed_markup_trying_to_break_out_of_the_chart_div_is_dropped_entirely():
    """Not valid XML (an unclosed/mismatched tag attempting to break out
    of the template's <div class="chart">...</div> wrapper) - must never
    be passed through raw; the whole chart is simply omitted."""
    payload = '</div><style>.disclaimer{display:none}</style><div>'
    assert sanitize_chart_svg(payload) == ""


def test_non_svg_root_element_is_dropped():
    assert sanitize_chart_svg('<div onclick="alert(1)">not a chart</div>') == ""


def test_doctype_with_external_entity_is_dropped_not_expanded():
    """XXE: an external/parameter entity declared in a DOCTYPE must never
    be resolved or leak into the output - defusedxml refuses to parse
    this at all, so it's dropped like any other unparsable input."""
    payload = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///app/.env">]>'
        "<svg><text>&xxe;</text></svg>"
    )
    result = sanitize_chart_svg(payload)
    assert "xxe" not in result.lower() or result == ""
    assert ".env" not in result


# --- Run 2 fix batch 1: the chart's text and colours must survive -------------------------------


def test_tick_label_text_survives_and_dy_is_kept():
    """The bug: Recharts writes every tick label as a <tspan>'s TEXT, and the
    cleaner copied tags and attributes but never the text, so all labels came out
    empty. dy (0.71em) is what places them under the axis."""
    svg = (
        '<svg><text x="72" y="300"><tspan x="72" dy="0.71em">0mo</tspan></text>'
        '<text x="30" y="20" text-anchor="end"><tspan x="30" dy="0.355em">RM 70k</tspan></text></svg>'
    )

    result = sanitize_chart_svg(svg)

    assert '<tspan x="72" dy="0.71em">0mo</tspan>' in result
    assert "<tspan x=\"30\" dy=\"0.355em\">RM 70k</tspan>" in result


def test_dx_is_kept_and_text_after_a_child_element_survives():
    svg = '<svg><text dx="3">before<tspan>inside</tspan>after</text></svg>'

    result = sanitize_chart_svg(svg)

    assert 'dx="3"' in result
    assert ">before<tspan>inside</tspan>after</text>" in result


def test_label_text_is_escaped_so_it_can_never_carry_markup():
    svg = "<svg><text><tspan>&lt;script&gt;alert(1)&lt;/script&gt; &amp; &lt;b&gt;x&lt;/b&gt;</tspan></text></svg>"

    result = sanitize_chart_svg(svg)

    assert "<script" not in result and "<b>" not in result
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in result
    assert "&amp;" in result


def test_text_of_a_dropped_element_is_dropped_with_it():
    svg = "<svg><script>alert(document.cookie)</script><style>.x{}</style><foreignObject>secret</foreignObject></svg>"

    result = sanitize_chart_svg(svg)

    assert "alert" not in result and "secret" not in result and ".x{}" not in result


@pytest.mark.parametrize(
    "paint",
    ["none", "currentColor", "#fff", "#4f39f6", "#4F39F6", "rgb(79, 57, 246)", "rgb(79 57 246)",
     "rgba(0, 0, 0, 0.5)", "rgb(10%, 20%, 30%)", "red", "Red", "slategrey", "url(#g1)", "transparent"],
)
def test_allowed_paints_are_kept_exactly(paint):
    for attribute in ("fill", "stroke", "stop-color"):
        result = sanitize_chart_svg(f'<svg><rect {attribute}="{paint}" x="0" y="0" width="1" height="1"/></svg>')
        assert f'{attribute}="{paint}"' in result


@pytest.mark.parametrize(
    "paint",
    ["var(--color-primary-600)", "var(--c, red)", "calc(1 + 1)", "url(http://evil.example/x.svg#a)",
     "url(file:///app/.env)", "url(data:image/svg+xml;base64,AAAA)", "expression(alert(1))", "javascript:alert(1)",
     "#12345", "#ggg", "rgb(1, 2)", "rgb(1, 2, 3", "oklch(0.5 0.2 270)", "red; fill: blue", "red\" onload=\"x",
     "notacolour", ""],
)
def test_anything_else_in_a_paint_is_replaced_with_the_grey_never_black(paint):
    for attribute in ("fill", "stroke", "stop-color"):
        element = svg_sanitizer.ET.Element("rect")
        svg = svg_sanitizer.ET.Element("svg")
        element.set(attribute, paint)
        svg.append(element)
        result = sanitize_chart_svg(svg_sanitizer.ET.tostring(svg, encoding="unicode"))
        assert f'{attribute}="{FALLBACK_PAINT}"' in result
        assert "var(" not in result and "evil.example" not in result and "onload" not in result
    assert FALLBACK_PAINT == "#444444"


def test_the_real_recharts_chart_keeps_every_label_and_loses_no_text():
    """The chart the browser really produced (tests/fixtures, 943px wide, 60 months)."""
    raw = (FIXTURES / "negative_equity_bmw_60.svg").read_text(encoding="utf-8")
    raw_labels = re.findall(r"<tspan[^>]*>([^<]*)</tspan>", raw)
    assert len(raw_labels) >= 29 and "0mo" in raw_labels and "60mo" in raw_labels and "RM 280k" in raw_labels

    result = sanitize_chart_svg(raw)

    assert re.findall(r"<tspan[^>]*>([^<]*)</tspan>", result) == raw_labels
    assert result.count('dy="0.71em"') == raw.count('dy="0.71em"') > 0
    assert "style=" not in result and "class=" not in result
    assert 'viewBox="0 0 943 320"' in result


def test_the_real_chart_with_unresolved_variables_comes_out_grey_not_black():
    raw = (FIXTURES / "negative_equity_bmw_60.svg").read_text(encoding="utf-8")
    assert "var(--color-primary-600)" in raw

    result = sanitize_chart_svg(raw)

    assert "var(" not in result
    assert FALLBACK_PAINT in result


def test_the_real_chart_with_resolved_colours_keeps_them():
    raw = (FIXTURES / "negative_equity_bmw_60.svg").read_text(encoding="utf-8")
    resolved = raw.replace("var(--color-primary-600)", "rgb(79, 57, 246)").replace(
        "var(--color-danger-600)", "rgb(231, 0, 11)")

    result = sanitize_chart_svg(resolved)

    assert 'stroke="rgb(79, 57, 246)"' in result and 'stroke="rgb(231, 0, 11)"' in result


def test_a_chart_over_the_element_cap_is_still_dropped_entirely(monkeypatch):
    monkeypatch.setattr(svg_sanitizer, "MAX_CHART_SVG_ELEMENTS", 5)
    svg = "<svg>" + "<text><tspan>1mo</tspan></text>" * 5 + "</svg>"

    assert sanitize_chart_svg(svg) == ""
