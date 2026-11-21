"""Test-only URLconf (used with @pytest.mark.urls): the real API plus one plain
Django view that raises, to exercise the middleware path. Never mounted by
config.urls."""

from django.urls import include, path


def plain_view_that_raises(request):
    raise RuntimeError("plain view failed (api_key=ABC123)")


urlpatterns = [
    path("plain-boom/", plain_view_that_raises),
    path("", include("config.urls")),
]
