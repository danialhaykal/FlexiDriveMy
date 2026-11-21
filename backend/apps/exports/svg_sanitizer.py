"""Sanitizes a client-supplied chart_svg before it is embedded verbatim
(unescaped) into the exported PDF's HTML (QA audit C4).

the project spec's architecture fixes Recharts specifically "because it survives
PDF export" by having the browser render the chart to real SVG markup,
which this backend then embeds directly (no rasterization, no JS runtime
here to re-render a chart itself) - so the input is inherently client-
controlled markup, not a value this backend can independently recompute.
The defence instead is: parse it as XML, rebuild a NEW tree containing
only an allowlisted set of inert, purely-visual SVG elements/attributes,
and re-serialize THAT tree - never the client's original string. This
closes every vector the audit named:

- `file://`/http(s) exfiltration or SSRF: every `href`/`xlink:href`
  attribute is dropped outright (covers <image>, <use>, <a>), and
  <image>/<foreignObject>/<iframe>/<object>/<embed>/<link> elements are
  dropped entirely regardless of their attributes.
- Hiding the legal disclaimer via injected CSS: every <style> element and
  every `style`/`class` attribute is dropped - nothing survives that
  could define or trigger a page-wide CSS rule.
- Breaking out of the `<div class="chart">...</div>` wrapper with
  malformed/non-SVG text: parsing requires well-formed XML, and the
  output is always re-serialized from the parsed-and-filtered tree, never
  the original string - unparsable or non-SVG input is simply dropped
  (the chart section is omitted), never passed through.
- XXE/entity-expansion attacks against the parser itself: parsed via
  defusedxml, not the stdlib parser directly.

Run 2 fix batch 1 (PDF chart):
- Text survives. The tick labels of a Recharts chart ("0mo", "RM 70k") are the
  TEXT of <tspan>/<text> elements; `text` and `tail` are copied onto the clean
  element. They are plain strings and ElementTree escapes them on output, so no
  markup can come through them (a "<script>" in a label is written as
  "&lt;script&gt;"). `dx`/`dy` are kept too - without `dy` the labels sit too high.
- Paint values (fill, stroke, stop-color) are checked. WeasyPrint has no app
  stylesheet, so a `var(--color-...)` the browser did not resolve would paint
  BLACK; any value that is not none / currentColor / #rgb / #rrggbb / rgb() /
  rgba() with plain numbers / a CSS colour name / url(#id) is replaced with a
  neutral grey (FALLBACK_PAINT), so an unresolved colour is visibly grey, never
  silently black, and nothing else can ride in a paint attribute.
"""

import logging
import re

import defusedxml.ElementTree as DefusedET
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

_SVG_NS = "http://www.w3.org/2000/svg"

# Run 1 fix batch 2 (G4): a chart with more elements than this is dropped (the
# PDF still exports, without it). Counted while sanitizing, so a huge chart
# stops being walked as soon as it passes the cap. The real negative-equity
# chart is at most 726 elements (108 months at 1024px, measured by
# NegativeEquityChart.size.test.tsx), so this leaves 6.9x. The request's byte
# cap is in apps.exports.serializers.MAX_CHART_SVG_BYTES.
MAX_CHART_SVG_ELEMENTS = 5_000

# Purely structural/visual elements a simple Recharts-style chart
# (bars/lines/axes/labels/gradients) actually needs. Deliberately excludes
# anything that can load external resources or run script:
# script/style/link/image/use/foreignObject/iframe/object/embed/a/
# animate*/set are all absent on purpose. Keyed by lowercased name (for
# case-insensitive lookup) -> the real, case-sensitive SVG spelling to
# write back out, since SVG is XML and several of these (clipPath,
# linearGradient, radialGradient) are only recognised by renderers in
# their canonical mixed-case form.
_ALLOWED_TAGS = {
    "svg": "svg", "g": "g", "path": "path", "rect": "rect", "circle": "circle",
    "ellipse": "ellipse", "line": "line", "polyline": "polyline", "polygon": "polygon",
    "text": "text", "tspan": "tspan", "defs": "defs",
    "lineargradient": "linearGradient", "radialgradient": "radialGradient",
    "stop": "stop", "clippath": "clipPath", "title": "title", "desc": "desc",
}

# Presentation/structural attributes only - no `style` (arbitrary CSS),
# no `href`/`xlink:href` (resource loading), no `on*` event handlers. Same
# lowercased-key -> canonical-spelling mapping as _ALLOWED_TAGS, for the
# same reason (viewBox, preserveAspectRatio, gradientUnits/Transform are
# case-sensitive).
_ALLOWED_ATTRS = {
    "id": "id", "viewbox": "viewBox", "width": "width", "height": "height",
    "x": "x", "y": "y", "dx": "dx", "dy": "dy", "x1": "x1", "y1": "y1", "x2": "x2", "y2": "y2",
    "cx": "cx", "cy": "cy", "r": "r", "rx": "rx", "ry": "ry", "d": "d",
    "points": "points", "transform": "transform", "offset": "offset",
    "fill": "fill", "fill-opacity": "fill-opacity", "fill-rule": "fill-rule",
    "stroke": "stroke", "stroke-width": "stroke-width", "stroke-opacity": "stroke-opacity",
    "stroke-linecap": "stroke-linecap", "stroke-linejoin": "stroke-linejoin",
    "stroke-dasharray": "stroke-dasharray", "opacity": "opacity",
    "font-size": "font-size", "font-family": "font-family", "font-weight": "font-weight",
    "text-anchor": "text-anchor", "dominant-baseline": "dominant-baseline",
    "stop-color": "stop-color", "stop-opacity": "stop-opacity",
    "gradientunits": "gradientUnits", "gradienttransform": "gradientTransform",
    "preserveaspectratio": "preserveAspectRatio", "clip-path": "clip-path",
}


# The attributes that carry a paint (a colour), checked by _safe_paint.
_PAINT_ATTRS = frozenset({"fill", "stroke", "stop-color"})

# What replaces a paint value that is not on the allowlist. A mid grey, not
# black: a colour the browser did not resolve must be visible as wrong.
FALLBACK_PAINT = "#444444"

_NUMBER = r"[+-]?(?:\d+\.?\d*|\.\d+)"
_HEX_PAINT = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")
_RGB_PAINT = re.compile(
    rf"rgba?\(\s*{_NUMBER}%?\s*[, ]\s*{_NUMBER}%?\s*[, ]\s*{_NUMBER}%?\s*(?:[,/]\s*{_NUMBER}%?\s*)?\)", re.IGNORECASE
)
_URL_PAINT = re.compile(r"url\(\s*#[A-Za-z_][\w:.-]*\s*\)(?:\s+(?:none|currentColor|#[0-9a-fA-F]{3,6}))?")
_KEYWORD_PAINTS = frozenset({"none", "currentcolor", "transparent"})

# The CSS named colours (CSS Color Level 4), lowercased.
_NAMED_COLORS = frozenset(
    "aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown "
    "burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan "
    "darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid "
    "darkred darksalmon darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet "
    "deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro "
    "ghostwhite gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki "
    "lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan lightgoldenrodyellow "
    "lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray "
    "lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine "
    "mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise "
    "mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab "
    "orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru "
    "pink plum powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown "
    "seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen steelblue tan "
    "teal thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen".split()
)


def _safe_paint(value):
    """`value` if it is an allowed paint, else FALLBACK_PAINT (see the module
    docstring). Anything with a var(), calc(), url to a file, expression or
    stray punctuation fails every pattern and is replaced."""
    text = value.strip()
    if (
        text.lower() in _KEYWORD_PAINTS
        or text.lower() in _NAMED_COLORS
        or _HEX_PAINT.fullmatch(text)
        or _RGB_PAINT.fullmatch(text)
        or _URL_PAINT.fullmatch(text)
    ):
        return text
    return FALLBACK_PAINT


def _local_name(tag):
    """Strips a `{namespace}localname` Clark-notation tag/attribute name
    down to just `localname`, lowercased - element/attribute names in SVG
    are case-sensitive in theory, but comparing case-insensitively here
    only makes the allowlist stricter in practice (an unexpected-case
    variant simply fails to match and gets dropped), never looser.
    """
    name = tag.rsplit("}", 1)[-1]
    return name.lower()


class _TooManyElements(Exception):
    pass


def _sanitize_element(element, budget):
    """Returns a new, filtered copy of `element`, or None if its own tag
    isn't allowed (the whole element - attributes and children - is
    dropped in that case, not just the tag). `budget` is a one-item list
    holding how many more elements may be visited; running out raises
    _TooManyElements."""
    budget[0] -= 1
    if budget[0] < 0:
        raise _TooManyElements

    canonical_tag = _ALLOWED_TAGS.get(_local_name(element.tag))
    if canonical_tag is None:
        return None

    clean = ET.Element(canonical_tag)
    for attr_name, attr_value in element.attrib.items():
        canonical_attr = _ALLOWED_ATTRS.get(_local_name(attr_name))
        if canonical_attr is not None:
            clean.set(canonical_attr, _safe_paint(attr_value) if canonical_attr in _PAINT_ATTRS else attr_value)

    # Run 2 fix batch 1: the chart's tick labels are element text. Plain
    # strings - ElementTree escapes them when the tree is serialized, so a
    # label can never carry markup.
    clean.text = element.text
    clean.tail = element.tail

    for child in element:
        clean_child = _sanitize_element(child, budget)
        if clean_child is not None:
            clean.append(clean_child)

    return clean


def sanitize_chart_svg(raw_svg):
    """Returns safe SVG markup to embed, or "" if `raw_svg` is blank,
    isn't parsable as well-formed XML, or its root element isn't an
    <svg> - "" is treated as "no chart" by the template (never a crash,
    never a pass-through of unsafe/unparsable input).
    """
    if not raw_svg or not raw_svg.strip():
        return ""

    try:
        root = DefusedET.fromstring(raw_svg)
    except Exception:
        logger.warning("Dropping chart_svg: not well-formed XML", exc_info=True)
        return ""

    if _local_name(root.tag) != "svg":
        logger.warning("Dropping chart_svg: root element was not <svg>")
        return ""

    try:
        clean_root = _sanitize_element(root, [MAX_CHART_SVG_ELEMENTS])
    except _TooManyElements:
        # Run 1 fix batch 2 (G4): drop the chart, keep the PDF.
        logger.warning("Dropping chart_svg: more than %s elements", MAX_CHART_SVG_ELEMENTS)
        return ""
    except RecursionError:
        # Nesting far deeper than any real chart (a few levels) - same outcome.
        logger.warning("Dropping chart_svg: nested too deeply")
        return ""
    if clean_root is None:
        return ""

    # xml.etree always prefixes a declared/default namespace back onto
    # the root when serializing a bare Element built via ET.Element() -
    # setting it explicitly keeps the output a plain, namespace-prefix-
    # free <svg ...> the same way Recharts itself emits it, and WeasyPrint
    # still recognises it as SVG via this default xmlns.
    clean_root.set("xmlns", _SVG_NS)
    return ET.tostring(clean_root, encoding="unicode")
