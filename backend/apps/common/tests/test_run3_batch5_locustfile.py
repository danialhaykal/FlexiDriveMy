"""Run 3 fix batch 5 (F-07): the load test reads the active cars and their own
minimum downpayments from the catalog (every page) instead of a hard-coded id list,
and its login is configurable. The helpers live in backend/loadtest/catalog.py,
loaded by path (the folder is not a package; locust itself is never imported here -
it monkey-patches the standard library)."""

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

LOADTEST = Path(__file__).resolve().parents[3] / "loadtest"


@pytest.fixture(scope="module")
def catalog():
    spec = importlib.util.spec_from_file_location("flexidrive_loadtest_catalog", LOADTEST / "catalog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_vehicle_id_or_fixed_downpayment_is_hard_coded():
    source = (LOADTEST / "locustfile.py").read_text(encoding="utf-8")

    assert "VEHICLE_IDS" not in source
    assert "DOWNPAYMENT =" not in source
    assert "vehicle_choices(" in source and "min_downpayment" in source


def test_the_cars_come_from_every_catalog_page_with_their_own_minimum(catalog):
    pages = {
        "http://h/api/vehicles/catalog/": {"next": "http://h/api/vehicles/catalog/?page=2", "results": [
            {"id": 5, "min_downpayment": "26780.00"}, {"id": 12, "min_downpayment": "143000.00"}]},
        "http://h/api/vehicles/catalog/?page=2": {"next": None, "results": [{"id": 16, "min_downpayment": "57500.00"}]},
    }

    choices = catalog.vehicle_choices(pages.__getitem__, "http://h/api/vehicles/catalog/")

    assert choices == [(5, "26780.00"), (12, "143000.00"), (16, "57500.00")]


def test_the_page_cap_stops_a_runaway_next_link(catalog):
    loop = {"next": "http://h/again", "results": [{"id": 1, "min_downpayment": "1.00"}]}

    assert len(catalog.vehicle_choices(lambda url: loop, "http://h/again")) == catalog.MAX_CATALOG_PAGES


def test_the_login_comes_from_the_two_variables(catalog):
    assert catalog.login_from_environment({"LOADTEST_EMAIL": " o@example.com ", "LOADTEST_PASSWORD": "pw-1"}) == (
        "o@example.com", "pw-1")


@pytest.mark.parametrize("environ, sentence", [
    ({}, "Set LOADTEST_EMAIL and LOADTEST_PASSWORD before running the load test."),
    ({"LOADTEST_PASSWORD": "pw-1"}, "Set LOADTEST_EMAIL before running the load test."),
    ({"LOADTEST_EMAIL": "o@example.com"}, "Set LOADTEST_PASSWORD before running the load test."),
    ({"LOADTEST_EMAIL": "o@example.com", "LOADTEST_PASSWORD": "  "}, "Set LOADTEST_PASSWORD before running the load test."),
    ({"LOADTEST_EMAIL": "", "LOADTEST_PASSWORD": ""}, "Set LOADTEST_EMAIL and LOADTEST_PASSWORD before running the load test."),
])
def test_a_missing_variable_stops_with_one_plain_sentence(catalog, environ, sentence):
    with pytest.raises(catalog.LoadTestConfigError) as excinfo:
        catalog.login_from_environment(environ)

    assert str(excinfo.value) == sentence
    assert "pw-1" not in str(excinfo.value)  # the password is never echoed


def test_no_password_is_kept_in_the_load_test_files(catalog):
    assert not hasattr(catalog, "DEFAULT_LOGIN_PASSWORD")
    for name in ("catalog.py", "locustfile.py", "README.md"):
        source = (LOADTEST / name).read_text(encoding="utf-8")
        assert not re.search(r"""PASSWORD\s*=\s*["'][^"'<]""", source), name  # only "<placeholder>" values
        assert "DEFAULT_LOGIN" not in source, name


def test_the_locustfile_fails_fast_without_the_variables():
    """Run in its own process: importing locust monkey-patches the standard library."""
    env = {k: v for k, v in os.environ.items() if k not in ("LOADTEST_EMAIL", "LOADTEST_PASSWORD")}
    result = subprocess.run(
        [sys.executable, "-c", "import locustfile"], cwd=LOADTEST, env=env, capture_output=True, text=True, timeout=120,
    )

    assert result.returncode == 1
    assert result.stderr.strip() == "Set LOADTEST_EMAIL and LOADTEST_PASSWORD before running the load test."


def test_the_catalog_endpoint_lists_only_active_cars_with_their_minimum(regular_user):
    """The real endpoint the test reads: active cars only, each with min_downpayment."""
    from rest_framework.test import APIClient

    from apps.vehicles.models import BodySegment, Brand, VehicleModel

    brand = Brand.objects.create(name="LoadBrand", tier_code="2")
    active = VehicleModel.objects.create(brand=brand, name="A", trim="X", body_segment=BodySegment.SEDAN,
                                         msrp="300000.00", engine_capacity_kw="150.00", powertrain="petrol",
                                         engine_capacity_cc=1998)
    VehicleModel.objects.create(brand=brand, name="B", trim="X", body_segment=BodySegment.SEDAN, msrp="300000.00",
                                engine_capacity_kw="150.00", powertrain="petrol", engine_capacity_cc=1998,
                                is_active=False)
    client = APIClient()
    client.force_authenticate(user=regular_user)

    page = client.get("/api/vehicles/catalog/").data

    assert [(car["id"], car["min_downpayment"]) for car in page["results"]] == [(active.pk, "30000.00")]


pytestmark = pytest.mark.django_db
