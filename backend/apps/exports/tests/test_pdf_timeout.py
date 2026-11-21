"""Tests render_pdf_with_timeout()'s timeout/failure handling by
monkeypatching _compile_pdf, so these run regardless of whether real
WeasyPrint compilation works in this environment (it doesn't, here - see
pdf.py's module docstring)."""

import time

import pytest

from apps.exports import pdf


def test_successful_compilation_returns_bytes(monkeypatch):
    monkeypatch.setattr(pdf, "_compile_pdf", lambda html: b"%PDF-1.7 fake bytes")

    result = pdf.render_pdf_with_timeout("<html></html>", timeout_seconds=5)

    assert result == b"%PDF-1.7 fake bytes"


def test_non_timeout_failure_raises_engine_unavailable_not_a_fabricated_timeout(monkeypatch):
    """QA audit C3b: a WeasyPrint/GTK failure (or any other non-timeout
    compilation exception, e.g. simulated memory exhaustion) must never
    be reported as "timeout" - that was simply false. It's a distinct
    exception type/message from a genuine timeout below.
    """

    def _raise(html):
        raise RuntimeError("simulated memory exhaustion")

    monkeypatch.setattr(pdf, "_compile_pdf", _raise)

    with pytest.raises(pdf.PDFEngineUnavailableError) as exc_info:
        pdf.render_pdf_with_timeout("<html></html>", timeout_seconds=5)

    assert str(exc_info.value) == pdf.ENGINE_UNAVAILABLE_MESSAGE


def test_compilation_timeout_raises_without_waiting_for_the_full_hang(monkeypatch):
    def _hang(html):
        time.sleep(2)
        return b"%PDF-1.7 too slow"

    monkeypatch.setattr(pdf, "_compile_pdf", _hang)

    started = time.monotonic()
    with pytest.raises(pdf.PDFCompilationTimeoutError) as exc_info:
        pdf.render_pdf_with_timeout("<html></html>", timeout_seconds=0.05)
    elapsed = time.monotonic() - started

    assert str(exc_info.value) == pdf.TIMEOUT_MESSAGE
    assert elapsed < 1.0  # fell back promptly, didn't wait out the 2s hang


def test_import_error_for_missing_gtk_is_engine_unavailable_not_a_timeout(monkeypatch):
    """The actual real-world failure mode on this dev machine: `import
    weasyprint` itself raises OSError because the GTK3 runtime isn't
    installed (see pdf.py's module docstring). Simulated here via
    _compile_pdf directly since the real import can't be forced to fail
    only sometimes within one test process.
    """

    def _raise(html):
        raise OSError("cannot load library libgobject-2.0-0: error 0x7e")

    monkeypatch.setattr(pdf, "_compile_pdf", _raise)

    with pytest.raises(pdf.PDFEngineUnavailableError) as exc_info:
        pdf.render_pdf_with_timeout("<html></html>", timeout_seconds=5)

    assert str(exc_info.value) == pdf.ENGINE_UNAVAILABLE_MESSAGE


# --- C4: no external resource fetching during PDF compilation --------------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "file:///app/.env",
        "http://169.254.169.254/latest/meta-data/",
        "https://example.com/tracker.png",
    ],
)
def test_blocking_url_fetcher_refuses_every_url(url):
    with pytest.raises(ValueError):
        pdf._blocking_url_fetcher(url)
