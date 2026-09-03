"""
Error pages that explain themselves.

Django's built-in CSRF failure page is a bare yellow 403 that says
"verification failed" and nothing a visitor can act on. On a demo that sleeps
after fifteen minutes and sits in people's tabs, the usual cause is simply a
stale page - so the page should say that, and offer the one click that fixes
it.
"""

import logging

from django.shortcuts import render

logger = logging.getLogger(__name__)


def csrf_failure(request, reason=""):
    """
    Rendered instead of Django's default when a CSRF check fails.

    Signature is fixed by CSRF_FAILURE_VIEW. Django's `reason` names the
    check that failed and the origins we trust, so it is logged rather than
    rendered - the visitor's question is "what do I do", and the answer does
    not depend on which check tripped.
    """
    logger.warning("CSRF failure on %s: %s", request.path, reason)
    return render(request, "portal/csrf_failure.html", status=403)
