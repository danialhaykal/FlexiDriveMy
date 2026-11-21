from decimal import Decimal

import pytest

from apps.vehicles import paultan_research as pr

# Faithful excerpt of the real rendered page
# https://paultan.org/research/bmw/3-series/g20-lci-2/330i-m-sport-2025/  (fetched 2026-10-06)
URL_330I_2025 = "https://paultan.org/research/bmw/3-series/g20-lci-2/330i-m-sport-2025/"
TITLE_330I_2025 = "BMW 3 Series 330i M Sport — RM313,800, specifications Malaysia — paultan.org"
TEXT_330I_2025 = """
Car Buyer's Guide
Compare
Brands
Tools
Home › Research › BMW › 3 Series › G20 LCI 2 › 330i M Sport
BMW 3 Series 330i M Sport
G20 LCI 2 · launched Jun 12 2025 · Sedan · CKD
No longer on sale — shown for reference
Colours — exterior
Alpine White Metallic
Powertrain
Engine Tech
16-valve DOHC direct injection with twin-scroll turbocharger, variable valve timing
Capacity
1,998 cc
Horsepower
258 hp at 5,000 rpm
Torque
400 Nm at 1,550 rpm
Fuel
Petrol
Dimensions
Seats
5
Cabin
Power Sockets
1 Front, 1 Centre Armrest, 1 Rear, 1 Boot
Comfort & access
Power Windows
Four Windows, Auto Up and Down with Anti Pinch
Price when on sale
RM313,800
OTR without insurance · no longer available
Other variants
320i Sport RM267,800
330i M Sport FAQ
The BMW 3 Series 330i M Sport was priced at RM313,800 OTR (Peninsular Malaysia, without insurance).
"""

# Same page if a renderer puts label/value in table cells (tab-separated)
TEXT_TAB_LAYOUT = """
G20 LCI 2 · launched Jun 12 2025 · Sedan · CKD
Capacity\t1,998 cc
Horsepower\t258 hp at 5,000 rpm
Power Windows\tFour Windows
Price when on sale\tRM313,800
"""


def test_full_extraction_real_page():
    r = pr.extract_variant_spec(URL_330I_2025, TITLE_330I_2025, TEXT_330I_2025)
    assert r.body_type == "Sedan"
    assert r.model_year == 2025
    assert r.msrp == Decimal("313800")
    assert r.engine_power_kw == Decimal("189.76")      # 258 PS * 0.7355 (BMW official: 190 kW)
    assert r.engine_capacity_cc == 1998
    assert r.missing_fields == []


def test_price_falls_back_to_price_box_when_title_missing():
    assert pr.extract_msrp("", TEXT_330I_2025) == Decimal("313800")


def test_price_falls_back_to_prose():
    assert pr.extract_msrp("", "It is priced at RM267,800 OTR.") == Decimal("267800")


def test_tab_layout_works_too():
    r = pr.extract_variant_spec(URL_330I_2025, "", TEXT_TAB_LAYOUT)
    assert (r.body_type, r.model_year, r.msrp, r.engine_power_kw) == (
        "Sedan", 2025, Decimal("313800"), Decimal("189.76"))


def test_power_label_never_matches_power_windows_or_sockets():
    text = "Power Windows\nFour Windows\nPower Sockets\n2 Front\n"
    assert pr.extract_engine_power_kw(text) is None


def test_kw_value_used_directly_for_evs():
    assert pr.extract_engine_power_kw("Motor Power\n150 kW") == Decimal("150.00")


def test_previous_regression_case_203ps():
    assert pr.extract_engine_power_kw("Horsepower\n203 PS") == Decimal("149.31")


# POWERTRAIN block of the live Porsche Macan Electric RWD page (single motor).
TEXT_EV_SINGLE_MOTOR = """
POWERTRAIN
Engine Tech
PPE platform, 800V architecture
Fuel
Electric
Number of Motors
1
Motor Horsepower
355 hp
Motor Torque
563 Nm
Battery Capacity
100 kWh
EV Range
641 km
Charging Rate (AC)
11 kW
Charging Rate (DC)
270 kW
DRIVETRAIN
"""

# Same block on the live Macan 4 page: two motors, ONE combined figure.
TEXT_EV_DUAL_MOTOR = TEXT_EV_SINGLE_MOTOR.replace("Number of Motors\n1", "Number of Motors\n2").replace(
    "355 hp", "405 hp"
)


# POWERTRAIN blocks of live pages (fetched 2026-10-07). paultan's "Fuel" line
# is the only powertrain signal: "Petrol", "Electric", "Petrol Plug-in
# Hybrid" are unambiguous; "Petrol Hybrid/REV" covers mild hybrids, full
# hybrids and range extenders alike.
TEXT_C200_HYBRID = """
POWERTRAIN
Engine Tech
16-valve DOHC, Turbocharged with Direct Fuel Injection and Variable Valve Timing
Capacity
1,496 cc
Horsepower
201 hp at 5,800 rpm
Fuel
Petrol Hybrid/REV
Number of Motors
1
Motor Horsepower
20 hp
DRIVETRAIN
"""

TEXT_C350E_PHEV = """
POWERTRAIN
Engine Tech
16-valve DOHC, Turbocharged with Direct Fuel Injection and Variable Valve Timing, Plug-in Hybrid Assist
Capacity
1,999 cc
Horsepower
204 hp at 5,800 rpm
Fuel
Petrol Plug-in Hybrid
Battery Capacity
25.4 kWh
DRIVETRAIN
"""

TEXT_VOLVO_MHEV = """
POWERTRAIN
Engine Tech
16-valve DOHC with Direct Fuel Injection, Turbocharger, Variable Valve Timing with MHEV Assistance
Capacity
1,969 cc
Horsepower
246 hp at 5,500 rpm
Fuel
Petrol Hybrid/REV
Motor Horsepower
13 hp
DRIVETRAIN
"""


@pytest.mark.parametrize(
    "text, expected",
    [
        (TEXT_330I_2025, "petrol"),
        (TEXT_EV_SINGLE_MOTOR, "bev"),
        (TEXT_C350E_PHEV, "phev"),
        (TEXT_VOLVO_MHEV, "mild_hybrid"),  # "Petrol Hybrid/REV" + an explicit "MHEV" in the engine description
        ("Fuel\nDiesel\n", "diesel"),
        (TEXT_C200_HYBRID, None),  # "Petrol Hybrid/REV" alone is ambiguous - the admin picks
        ("Fuel\nPetrol Hybrid/REV\n", None),
        ("Capacity\n1,998 cc\n", None),  # no Fuel line at all - never guessed from the cc
        ("Fuel\n6.5 l/100 km\n", None),
        ("", None),
    ],
    ids=["petrol", "bev", "phev", "mhev-marker", "diesel", "c200-ambiguous", "hybrid-rev-bare", "no-fuel", "not-a-fuel", "empty"],
)
def test_extract_powertrain_is_conservative(text, expected):
    assert pr.extract_powertrain(text) == expected


def test_extract_engine_capacity_cc_reads_petrol_and_returns_none_for_an_ev():
    assert pr.extract_engine_capacity_cc(TEXT_330I_2025) == 1998
    assert pr.extract_engine_capacity_cc(TEXT_EV_SINGLE_MOTOR) is None


def test_variant_spec_carries_powertrain_and_cc_without_changing_its_missing_fields():
    result = pr.extract_variant_spec(URL_330I_2025, TITLE_330I_2025, TEXT_330I_2025)
    assert (result.powertrain, result.engine_capacity_cc) == ("petrol", 1998)
    assert result.missing_fields == []


def test_single_motor_ev_reads_motor_horsepower():
    assert pr.extract_engine_power_kw(TEXT_EV_SINGLE_MOTOR) == Decimal("261.10")  # 355 * 0.7355


def test_dual_motor_ev_uses_the_combined_motor_horsepower():
    assert pr.extract_engine_power_kw(TEXT_EV_DUAL_MOTOR) == Decimal("297.88")  # 405 * 0.7355


def test_mild_hybrid_still_takes_engine_horsepower_over_motor_horsepower():
    # Mercedes C200: 201 hp engine + 20 hp 48V motor. The motor line comes
    # first here to prove label order, not line order, decides.
    text = "Motor Horsepower\n20 hp\nHorsepower\n201 hp\n"
    assert pr.extract_engine_power_kw(text) == Decimal("147.84")  # 201 * 0.7355


def test_ev_charging_rate_kw_is_never_taken_as_power():
    text = TEXT_EV_SINGLE_MOTOR.replace("Motor Horsepower\n355 hp\n", "")
    assert pr.extract_engine_power_kw(text) is None


def test_unknown_body_type_is_not_guessed():
    assert pr.extract_body_type("X · launched Jan 1 2025 · Spaceship · CBU") is None


def test_all_blank_when_nothing_present():
    r = pr.extract_variant_spec("https://paultan.org/research/bmw/", "", "Just some news prose.")
    assert r.missing_fields == ["body_type", "model_year", "msrp", "engine_power_kw"]


def test_year_from_launch_line_if_url_not_variant():
    assert pr.extract_model_year("https://paultan.org/research/bmw/3-series/",
                                 "G20 · launched Oct 17 2019 · Sedan · CKD") == 2019


# ---- listings (link text as found on the real brand/model pages)

MODEL_PAGE_LINKS = [
    ("https://paultan.org/research/bmw/3-series/g20-lci-2/320i-sport-2026/",
     "BMW 3 Series 320i Sport\n2026 · 1,998 cc · 184 hp · Petrol · RWD · Automatic · 5 seats · CKD\nRM267,800\nRM2,735/mo est."),
    ("https://paultan.org/research/bmw/3-series/g20-lci-2/320i-sport-2026/",
     "Full specifications & gallery →"),
    ("https://paultan.org/research/bmw/3-series/g20-lci-2/330i-m-sport-2026/",
     "BMW 3 Series 330i M Sport\n2026 · 1,998 cc · 258 hp · Petrol · RWD · Automatic · 5 seats · CKD\nRM316,800"),
    ("https://paultan.org/research/bmw/3-series/g20-lci-2/330i-m-sport-2025/",
     "BMW 3 Series 330i M Sport 2025 · 1,998 cc · 258 hp · Petrol · RWD · Automatic · 5 seats · CKD RM313,800 No longer on sale"),
    ("https://paultan.org/research/compare/bmw-3-series/320i-sport-2026-vs-330i-m-sport-2026/",
     "320i Sport vs 330i M Sport"),
    ("https://paultan.org/research/mercedes-benz/c-class/", "Mercedes-Benz C-Class ... RM292,888"),
]


def test_variant_listing():
    v = pr.parse_variant_links(MODEL_PAGE_LINKS, "bmw", "3-series")
    assert [x["name"] for x in v] == [
        "BMW 3 Series 320i Sport", "BMW 3 Series 330i M Sport", "BMW 3 Series 330i M Sport"]
    assert [x["year"] for x in v] == [2026, 2026, 2025]
    assert [x["on_sale"] for x in v] == [True, True, False]
    assert v[0]["msrp"] == "267800" and v[0]["power_hp"] == 184


BRAND_PAGE_LINKS = [
    ("https://paultan.org/research/bmw/3-series/",
     "BMW 3 Series BMW 3 Series Sedan Compact Executive Launched Jan 20 2025RM267,800–RM323,800"),
    ("https://paultan.org/research/bmw/x1/", "BMW X1\nSUV\nC-Segment\nLaunched Oct 9 2023\nRM252,800"),
    ("https://paultan.org/research/bmw/ev/", "BMW electric cars →"),
    ("https://paultan.org/research/body/sedan/", "Sedan"),
    ("https://paultan.org/research/bmw/", "BMW"),
]


def test_model_listing():
    m = pr.parse_model_links(BRAND_PAGE_LINKS, "bmw")
    assert [x["name"] for x in m] == ["BMW 3 Series", "BMW X1"]
    assert m[0]["price_text"] == "RM267,800–RM323,800"


@pytest.mark.parametrize("brand,slug", [
    ("BMW", "bmw"), ("Mercedes-Benz", "mercedes-benz"), ("Mercedes", "mercedes-benz"),
    ("Land Rover", "land-rover"), ("GWM", "great-wall"), ("Porsche", "porsche"), ("Lexus", "lexus"),
])
def test_brand_slugs(brand, slug):
    assert pr.brand_slug(brand) == slug


@pytest.mark.parametrize("url,ok", [
    ("https://paultan.org/research/bmw/3-series/", True),
    ("http://paultan.org/research/bmw/", False),
    ("https://paultan.org.evil.com/research/", False),
    ("https://paultan.org/2025/01/20/some-news/", False),
    ("https://paultan.org:8080/research/", False),
    ("https://169.254.169.254/research/", False),
])
def test_ssrf_guard(url, ok):
    assert pr.is_allowed_research_url(url) is ok
