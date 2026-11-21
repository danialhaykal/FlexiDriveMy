"""F008 - WeasyPrint HTML->PDF compilation with a timeout (UC008 alt flow:
compilation timeout or memory exhaustion), mirroring the same
ThreadPoolExecutor + future.result(timeout=...) pattern used for F006's
ML inference timeout.

weasyprint is imported *lazily*, inside _compile_pdf(), not at module
level. Its native GObject/Pango/cairo dependency isn't installed
everywhere (notably: not on Windows without a separate GTK3 runtime
install - confirmed missing on this dev machine, `import weasyprint`
raises OSError there, and a winget install of the GTK3 runtime couldn't
complete in this sandboxed/non-interactive environment either - its
installer needs UAC elevation, which has no interactive desktop to
prompt on here). Importing it at module level would crash the whole app
on load wherever that's true; deferring the import means only an actual
PDF-generation attempt fails, and it fails through this module's own
PDFCompilationError subclasses so the caller's handling is identical in
shape whether the underlying cause is a real timeout, memory exhaustion,
or the rendering engine being unavailable in this environment - but
distinguishes WHICH of those happened (QA audit C3b: a missing-dependency
failure was previously mislabeled as a timeout, which is simply false).
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

logger = logging.getLogger(__name__)

TIMEOUT_MESSAGE = "PDF export failed due to a server generation timeout. Please try downloading again."
ENGINE_UNAVAILABLE_MESSAGE = (
    "PDF export isn't available in this environment right now. Please try again later."
)


class PDFCompilationError(Exception):
    """UC008 alt flow 3.1-3.3: caught by the caller, never an unhandled 500."""


class PDFCompilationTimeoutError(PDFCompilationError):
    """The compile genuinely ran out of time within timeout_seconds."""


class PDFEngineUnavailableError(PDFCompilationError):
    """WeasyPrint itself couldn't render - most commonly its native
    GObject/Pango/cairo dependency (the GTK3 runtime on Windows) isn't
    installed, but this also covers any other WeasyPrint-internal
    rendering failure. Never report this as a timeout - the real
    exception is logged here for admins; only the honest, generic
    message above reaches the client.
    """


def _blocking_url_fetcher(url):
    """C4: this app's report template is fully self-contained (inline SVG,
    system fonts) - it never legitimately needs to fetch anything.
    Refusing every fetch closes off `file://` reads of server files (e.g.
    .env) and server-side-request-forgery against internal http(s) URLs
    via a crafted chart_svg or any other field that ends up in the
    template. Raising here is WeasyPrint's documented way for a fetch to
    fail: the resource is simply dropped (logged), the render continues -
    never a crash.
    """
    raise ValueError(f"External resource fetching is disabled for PDF export: {url}")


def _compile_pdf(html_string):
    from weasyprint import HTML

    return HTML(string=html_string, url_fetcher=_blocking_url_fetcher).write_pdf()


def render_pdf_with_timeout(html_string, timeout_seconds):
    """Returns PDF bytes, or raises a PDFCompilationError subclass - never
    an unhandled exception. PDFCompilationTimeoutError for a genuine
    timeout; PDFEngineUnavailableError for everything else (the engine
    being unavailable, or any other WeasyPrint rendering failure) - the
    caller must never report the latter as a timeout.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_compile_pdf, html_string)
    try:
        pdf_bytes = future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        # Don't wait for a hung/slow compile to finish before reporting
        # failure - shutdown(wait=False) lets it die in the background.
        executor.shutdown(wait=False)
        raise PDFCompilationTimeoutError(TIMEOUT_MESSAGE) from exc
    except Exception as exc:
        executor.shutdown(wait=False)
        logger.exception("PDF compilation failed (not a timeout) - engine unavailable or a rendering error")
        raise PDFEngineUnavailableError(ENGINE_UNAVAILABLE_MESSAGE) from exc
    executor.shutdown(wait=False)
    return pdf_bytes
