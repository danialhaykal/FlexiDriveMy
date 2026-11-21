"""
paultan.org Car Buyer's Guide (/research/) spec extraction for FlexiDriveMy F010 "Fetch Spec Draft".

WHY THIS EXISTS
  The old approach searched paultan.org news articles and looked for "Label: value" lines.
  News articles are prose, so nothing matched. paultan.org also runs a structured buyer's
  guide under /research/ with a fixed hierarchy:

      /research/<brand>/                                  brand page   -> list of models
      /research/<brand>/<model>/                          model page   -> list of variants (+ price, hp, cc)
      /research/<brand>/<model>/<gen>/<variant>-<year>/   variant page -> full spec sheet

  On a variant page, specs are laid out as a LABEL on one line and its VALUE on the next
  (e.g. "Horsepower" / "258 hp at 5,000 rpm"), never "Label: value". This module parses
  that layout, plus two even more stable hooks: the page <title> (always carries the price)
  and the header line ("G20 LCI 2 · launched Jun 12 2025 · Sedan · CKD").

Everything except render_research_page() is pure text/regex, so it is unit-testable offline.
Fields are left as None when not found. Nothing is guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional
from urllib.parse import urlparse

RESEARCH_HOST = "paultan.org"
RESEARCH_ROOT = "https://paultan.org/research/"

# Same factor the existing PS->kW converter uses (203 PS -> 149.31 kW).
# paultan's "hp" is NOT consistently PS: BMW 320i is listed as 184 hp (BMW's
# 184 PS / 135 kW), but Mercedes C200's 201 hp is mechanical hp for 150 kW and
# Porsche Macan RWD's 355 hp is mechanical hp for 265 kW. Treating every "hp"
# as PS under-reads mechanical-hp figures by under 1.5% (355 hp -> 261.10 kW vs
# the official 265 kW). That tolerance is accepted rather than per-brand logic:
# every draft is reviewed (and editable) by an admin before anything is saved.
PS_TO_KW = Decimal("0.7355")

# Body types exactly as paultan's own search filters name them. Strict set: no guessing.
KNOWN_BODY_TYPES = {
    "sedan", "hatchback", "mpv", "suv", "pickup", "wagon", "coupe",
    "convertible", "commercial", "van",
}

# Brand names that don't slugify to paultan's real slug (taken from the site's make filter).
BRAND_SLUG_ALIASES = {
    "mercedes": "mercedes-benz",
    "mercedes benz": "mercedes-benz",
    "merc": "mercedes-benz",
    "gwm": "great-wall",
    "great wall": "great-wall",
    "omoda": "jaecoo",
    "omoda jaecoo": "jaecoo",
    "jaecoo": "jaecoo",
    "vw": "volkswagen",
}

# Run 1 fix batch 5 (D3): model, generation and variant slugs may contain dots
# ("alphard/ah40/2.4-executive-lounge-2026"). The host and /research/ path are
# fixed, each segment starts with a letter or digit, and ".." is refused
# anywhere, so the guard is as tight as before.
_VARIANT_URL_RE = re.compile(
    r"^(?!.*\.\.)https://paultan\.org/research/(?P<brand>[a-z0-9-]+)/(?P<model>[a-z0-9][a-z0-9.-]*)/"
    r"(?P<gen>[a-z0-9][a-z0-9.-]*)/(?P<variant>[a-z0-9][a-z0-9.-]*?)-(?P<year>(?:19|20)\d{2})/?$"
)
_MODEL_URL_RE = re.compile(
    r"^https://paultan\.org/research/(?P<brand>[a-z0-9-]+)/(?P<model>[a-z0-9-]+)/?$"
)
_NON_MODEL_SLUGS = {"ev", "gallery", "compare", "search", "brands", "tools"}

_RM_RE = re.compile(r"RM\s?([\d,]{4,})")
_POWER_RE = re.compile(r"([\d][\d,]*(?:\.\d+)?)\s*(kW|PS|hp|bhp)\b", re.I)
_LAUNCHED_YEAR_RE = re.compile(r"launched\s+\w+\s+\d{1,2}\s+((?:19|20)\d{2})", re.I)

MSRP_MIN = Decimal("10000")
MSRP_MAX = Decimal("10000000")


# --------------------------------------------------------------------------- URLs

def brand_slug(brand: str) -> str:
    key = " ".join(brand.lower().replace("-", " ").split())
    if key in BRAND_SLUG_ALIASES:
        return BRAND_SLUG_ALIASES[key]
    return re.sub(r"[^a-z0-9]+", "-", key).strip("-")


def brand_page_url(brand: str) -> str:
    return f"{RESEARCH_ROOT}{brand_slug(brand)}/"


def is_allowed_research_url(url: str) -> bool:
    """SSRF guard: only ever fetch https://paultan.org/research/... URLs."""
    try:
        u = urlparse(url)
    except ValueError:
        return False
    return (
        u.scheme == "https"
        and u.hostname == RESEARCH_HOST
        and u.port is None
        and u.path.startswith("/research/")
        and ".." not in u.path
    )


def _clean_href(href: str) -> str:
    return href.split("#", 1)[0].split("?", 1)[0]


def is_variant_url(url: str) -> bool:
    return bool(_VARIANT_URL_RE.match(_clean_href(url)))


# ----------------------------------------------------------------- text helpers

def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def find_labeled_value(text: str, labels: Iterable[str]) -> Optional[str]:
    """
    Value for the first matching label. Handles all three layouts a renderer may produce:
      "Horsepower\\n258 hp"   (label and value on separate lines - what paultan renders)
      "Horsepower\\t258 hp"   (table cells -> inner_text uses tabs)
      "Horsepower: 258 hp"    (classic)
    A label must be the WHOLE line or be followed by a separator, so "Power" never
    matches "Power Windows".
    """
    lines = _lines(text)
    for label in labels:
        same_line = re.compile(
            rf"^{re.escape(label)}\s*(?::|\t| - | – |\s{{2,}})\s*(?P<v>.+)$", re.I
        )
        whole = re.compile(rf"^{re.escape(label)}\s*:?$", re.I)
        for i, ln in enumerate(lines):
            m = same_line.match(ln)
            if m:
                return m.group("v").strip()
            if whole.match(ln) and i + 1 < len(lines):
                return lines[i + 1]
    return None


def _header_parts(text: str) -> Optional[list[str]]:
    """The 'G20 LCI 2 · launched Jun 12 2025 · Sedan · CKD' line, split on '·'."""
    for ln in _lines(text):
        if "·" in ln and re.search(r"\blaunched\b", ln, re.I):
            return [p.strip() for p in ln.split("·") if p.strip()]
    return None


def _to_decimal_rm(raw: str) -> Optional[Decimal]:
    try:
        val = Decimal(raw.replace(",", ""))
    except Exception:
        return None
    return val if MSRP_MIN <= val <= MSRP_MAX else None


# ------------------------------------------------------------------- extractors

def extract_body_type(text: str) -> Optional[str]:
    parts = _header_parts(text)
    if not parts:
        return None
    for i, p in enumerate(parts):
        if p.lower().startswith("launched") and i + 1 < len(parts):
            cand = parts[i + 1]
            return cand if cand.lower() in KNOWN_BODY_TYPES else None
    # header without a launch part: take the first known body type in it
    for p in parts:
        if p.lower() in KNOWN_BODY_TYPES:
            return p
    return None


def extract_model_year(url: str, text: str) -> Optional[int]:
    m = _VARIANT_URL_RE.match(_clean_href(url or ""))
    if m:
        return int(m.group("year"))  # model year as paultan files it (slug suffix)
    m = _LAUNCHED_YEAR_RE.search(text or "")
    return int(m.group(1)) if m else None


def extract_msrp(title: str, text: str) -> Optional[Decimal]:
    # 1) <title>: "BMW 3 Series 330i M Sport — RM313,800, specifications Malaysia — paultan.org"
    m = re.search(r"—\s*RM\s?([\d,]{4,})", title or "")
    if m and (v := _to_decimal_rm(m.group(1))) is not None:
        return v
    # 2) price box: "Price when on sale" / "RM313,800"   (or "Price" on current models)
    raw = find_labeled_value(text, ["Price when on sale", "Price", "Harga"])
    if raw and (m := _RM_RE.search(raw)) and (v := _to_decimal_rm(m.group(1))) is not None:
        return v
    # 3) prose: "... is priced at RM313,800 OTR ..."
    m = re.search(r"priced at\s+RM\s?([\d,]{4,})", text or "", re.I)
    if m:
        return _to_decimal_rm(m.group(1))
    return None


def extract_engine_power_kw(text: str) -> Optional[Decimal]:
    # "Motor Horsepower" is last on purpose: EV pages only have that one, but
    # mild-hybrid pages have both, and plain "Horsepower" (the engine) must win
    # there. Labels are line-anchored, so "Horsepower" never matches the
    # "Motor Horsepower" line. Dual-motor EVs (e.g. Macan 4/Turbo) list one
    # combined "Motor Horsepower" figure, which is used as-is.
    raw = find_labeled_value(
        text,
        ["Horsepower", "Max Power", "Power Output", "Motor Power", "Power", "Motor Horsepower"],
    )
    if not raw:
        return None
    m = _POWER_RE.search(raw)
    if not m:
        return None
    num = Decimal(m.group(1).replace(",", ""))
    unit = m.group(2).lower()
    kw = num if unit == "kw" else num * PS_TO_KW
    if not (Decimal("20") <= kw <= Decimal("1500")):
        return None
    return kw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def extract_engine_capacity_cc(text: str) -> Optional[int]:
    """Engine displacement in cc. EVs have no capacity line -> None (which is
    correct, not missing - see apps.vehicles.tasks)."""
    raw = find_labeled_value(text, ["Capacity"])
    m = re.search(r"([\d,]+)\s*cc", raw or "")
    return int(m.group(1).replace(",", "")) if m else None


# The page's "Fuel" line, matched EXACTLY (case-insensitive) against the only
# values seen on real pages that name one powertrain unambiguously:
#   "Petrol"                -> petrol
#   "Electric"              -> bev
#   "Petrol Plug-in Hybrid" -> phev
#   "Diesel"                -> diesel   (exact label; no diesel page was
#                                        available to confirm it live)
# "Petrol Hybrid/REV" is deliberately NOT here: paultan uses it for mild
# hybrids (Mercedes C200, Volvo B5), full hybrids and range extenders alike.
_FUEL_TO_POWERTRAIN = {
    "petrol": "petrol",
    "electric": "bev",
    "petrol plug-in hybrid": "phev",
    "diesel": "diesel",
}


def extract_powertrain(text: str) -> Optional[str]:
    """One of apps.vehicles.models.Powertrain's values, or None when the page
    doesn't say clearly - the admin then picks it. Never guesses.

    "Petrol Hybrid/REV" alone is ambiguous (see above) and stays None, unless
    the engine description itself names the technology as "MHEV" (e.g. Volvo's
    "...Variable Valve Timing with MHEV Assistance"), which is explicit.
    """
    fuel = (find_labeled_value(text, ["Fuel"]) or "").strip().lower()
    if fuel in _FUEL_TO_POWERTRAIN:
        return _FUEL_TO_POWERTRAIN[fuel]
    if fuel == "petrol hybrid/rev":
        engine_tech = find_labeled_value(text, ["Engine Tech"]) or ""
        if re.search(r"\bMHEV\b", engine_tech):
            return "mild_hybrid"
    return None


@dataclass
class SpecDraftResult:
    source_url: str
    body_type: Optional[str] = None
    model_year: Optional[int] = None
    msrp: Optional[Decimal] = None
    engine_power_kw: Optional[Decimal] = None
    engine_capacity_cc: Optional[int] = None
    powertrain: Optional[str] = None
    missing_fields: list[str] = field(default_factory=list)


def extract_variant_spec(url: str, title: str, text: str) -> SpecDraftResult:
    r = SpecDraftResult(source_url=url)
    r.body_type = extract_body_type(text)
    r.model_year = extract_model_year(url, text)
    r.msrp = extract_msrp(title, text)
    r.engine_power_kw = extract_engine_power_kw(text)
    r.engine_capacity_cc = extract_engine_capacity_cc(text)
    r.powertrain = extract_powertrain(text)
    # missing_fields keeps its original four names; apps.vehicles.tasks
    # decides powertrain/cc, since "cc missing" depends on the powertrain
    # (a BEV correctly has none).
    for name in ("body_type", "model_year", "msrp", "engine_power_kw"):
        if getattr(r, name) is None:
            r.missing_fields.append(name)
    return r


# -------------------------------------------------------------- listing parsers

def _first_line_name(link_text: str) -> str:
    txt = re.sub(r"no longer on sale", " ", link_text, flags=re.I)
    first = next((ln.strip() for ln in txt.splitlines() if ln.strip()), "")
    words = first.split()
    for k in range(1, len(words) // 2 + 1):  # "BMW X1 BMW X1 SUV ..." -> "BMW X1"
        if words[:k] == words[k:2 * k]:
            return " ".join(words[:k])
    return first


def parse_model_links(links: Iterable[tuple[str, str]], brand_slug_: str) -> list[dict]:
    """From a brand page: [{name, url, price_text, on_sale}] (deduped by URL)."""
    out: dict[str, dict] = {}
    for href, txt in links:
        url = _clean_href(href)
        m = _MODEL_URL_RE.match(url)
        if not m or m["brand"] != brand_slug_ or m["model"] in _NON_MODEL_SLUGS:
            continue
        flat = " ".join((txt or "").split())
        if "RM" not in flat:  # model cards always carry a price; nav/news links don't
            continue
        if url in out:
            continue
        price = re.search(r"RM[\d,]+(?:\s*[–-]\s*RM[\d,]+)?", flat)
        out[url] = {
            "name": _first_line_name(txt) or m["model"].replace("-", " ").title(),
            "url": url if url.endswith("/") else url + "/",
            "price_text": price.group(0) if price else "",
            "on_sale": "no longer on sale" not in flat.lower(),
        }
    return list(out.values())


def parse_variant_links(
    links: Iterable[tuple[str, str]], brand_slug_: str, model_slug: str
) -> list[dict]:
    """
    From a model page: [{name, url, year, msrp, power_hp, on_sale}], on-sale first,
    newest year first, then cheapest. Cards look like:
      "BMW 3 Series 320i Sport 2026 · 1,998 cc · 184 hp · Petrol · RWD · ... RM267,800"
    """
    out: dict[str, dict] = {}
    for href, txt in links:
        url = _clean_href(href)
        m = _VARIANT_URL_RE.match(url)
        if not m or m["brand"] != brand_slug_ or m["model"] != model_slug:
            continue
        flat = " ".join((txt or "").split())
        if "·" not in flat:  # skip "Full specifications & gallery →" duplicates
            continue
        year = int(m["year"])
        name_m = re.match(rf"^(.*?)\s+{year}\s*·", flat)
        price = _RM_RE.search(flat)
        hp = re.search(r"([\d,]+)\s*hp\b", flat, re.I)
        out.setdefault(url, {
            "name": (name_m.group(1) if name_m else m["variant"]).replace("No longer on sale", "").strip(),
            "url": url if url.endswith("/") else url + "/",
            "generation": m["gen"],
            "year": year,
            "msrp": str(_to_decimal_rm(price.group(1))) if price else None,
            "power_hp": int(hp.group(1).replace(",", "")) if hp else None,
            "on_sale": "no longer on sale" not in flat.lower(),
        })
    return sorted(
        out.values(),
        key=lambda v: (not v["on_sale"], -v["year"], Decimal(v["msrp"] or "0")),
    )


def model_slug_from_url(model_url: str) -> Optional[tuple[str, str]]:
    m = _MODEL_URL_RE.match(_clean_href(model_url))
    return (m["brand"], m["model"]) if m else None


# --------------------------------------------------------------------- fetching

def render_research_page(url: str, timeout_ms: int = 20000) -> dict:
    """
    The ONLY network function. Renders a /research/ page with Playwright and returns
    {status, final_url, title, text, links}. Keeps wait_until="load" (networkidle timed
    out inside Django's request thread - see the earlier fix).
    """
    if not is_allowed_research_url(url):
        raise ValueError(f"Refusing to fetch non-paultan-research URL: {url!r}")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 FlexiDriveMy-FYP-admin"
                )
            )
            resp = page.goto(url, wait_until="load", timeout=timeout_ms)
            return {
                "status": resp.status if resp else None,
                "final_url": page.url,
                "title": page.title(),
                "text": page.inner_text("body"),
                "links": page.eval_on_selector_all(
                    "a[href]", "els => els.map(e => [e.href, e.innerText || ''])"
                ),
            }
        finally:
            browser.close()
