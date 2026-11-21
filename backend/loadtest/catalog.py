"""Plain helpers for locustfile.py (no locust import, so they can be unit-tested -
importing locust monkey-patches the standard library through gevent)."""

import os

CATALOG_PATH = "/api/vehicles/catalog/"
MAX_CATALOG_PAGES = 100
LOGIN_VARIABLES = ("LOADTEST_EMAIL", "LOADTEST_PASSWORD")


class LoadTestConfigError(Exception):
    """A setting the load test needs is missing; str() is the one plain sentence to show."""


def login_from_environment(environ=None):
    """(email, password) from LOADTEST_EMAIL and LOADTEST_PASSWORD. There is no built-in
    default: if either is missing or empty, raises LoadTestConfigError naming the variable(s)
    to set. The password is never printed or logged."""
    environ = os.environ if environ is None else environ
    missing = [name for name in LOGIN_VARIABLES if not (environ.get(name) or "").strip()]
    if missing:
        raise LoadTestConfigError(f"Set {' and '.join(missing)} before running the load test.")
    return environ["LOADTEST_EMAIL"].strip(), environ["LOADTEST_PASSWORD"]


def vehicle_choices(get_json, first_url):
    """[(vehicle id, its own minimum downpayment as the API wrote it), ...] for every car
    the catalog lists (the catalog shows active cars only), following `next` page by
    page, at most MAX_CATALOG_PAGES pages. `get_json(url)` returns one page's JSON."""
    choices, url, pages = [], first_url, 0
    while url and pages < MAX_CATALOG_PAGES:
        page = get_json(url)
        choices.extend((car["id"], car["min_downpayment"]) for car in page.get("results", []))
        url, pages = page.get("next"), pages + 1
    return choices
