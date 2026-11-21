"""Run 1 fix batch 4 (UC013): unhandled errors from web requests go into the
audit log as "runtime_error" rows (apps.audit.services.log_runtime_error).

Two hooks, so every request path is covered:

  - api_exception_handler (REST_FRAMEWORK["EXCEPTION_HANDLER"]): DRF views.
    An APIException (validation, 404, permission, throttling...) is DRF's
    normal 4xx handling - never logged. Anything else is an unhandled error:
    logged, then left to Django's normal 500 handling exactly as before.
  - RuntimeErrorAuditMiddleware.process_exception: any view's exception that
    escapes the view (the non-DRF views).

log_runtime_error marks each exception it has seen, so an error is never
logged twice - not by both hooks, and not again after a failed background
task (e.g. ML training, run inline in dev) already logged it. Neither hook
changes the response: Django still returns its plain 500.
"""

from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework.exceptions import ValidationError
from rest_framework.views import exception_handler as drf_exception_handler

from apps.common.error_messages import labels_for_view, plain_error_messages

from .services import log_runtime_error


def api_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        # DRF had no response for it: an unhandled error that becomes a 500.
        log_runtime_error(source="api", error=exc, request=context.get("request"), status=500)
    elif isinstance(exc, ValidationError):
        # Run 2 fix batch 3 / Run 3 fix batch 5 (F-02): DRF's default sentences
        # ("A valid number is required.", "This field is required.") become
        # plain ones naming the field (the view's serializer labels when it has
        # one), for every serializer. Same keys, same status code; messages a
        # serializer wrote are untouched.
        response.data = plain_error_messages(response.data, labels=labels_for_view(context.get("view")))
    return response


class RuntimeErrorAuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        # 404 / 403 are handled responses, not runtime errors.
        if not isinstance(exception, (Http404, PermissionDenied)):
            log_runtime_error(source="web", error=exception, request=request, status=500)
        return None
