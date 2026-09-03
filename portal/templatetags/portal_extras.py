"""Small presentation filters shared by the portal templates."""

import os
from decimal import Decimal, InvalidOperation

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.utils.http import urlencode

register = template.Library()


@register.simple_tag
def static_v(path):
    """
    {% static %} plus a ?v=<mtime> cache buster.

    The dev server serves static files with only a Last-Modified header, so
    browsers hold on to old CSS/JS across edits. Stamping the file's mtime into
    the URL makes every change a new URL, which no browser can serve stale.
    """
    url = static(path)
    try:
        absolute = finders.find(path)
        if absolute and os.path.exists(absolute):
            return f"{url}?v={int(os.path.getmtime(absolute))}"
    except Exception:
        pass          # collectstatic/manifest storage - the hashed name is enough
    return url


@register.filter
def money(value):
    """1234.5 -> $1,234.50, and -1234.5 -> -$1,234.50 (not $-1,234.50)"""
    try:
        n = Decimal(value)
    except (TypeError, InvalidOperation):
        return value
    sign = "-" if n < 0 else ""
    return f"{sign}${abs(n):,.2f}"


@register.filter
def money0(value):
    """1234.5 -> $1,235 (whole dollars, for payout headlines)"""
    try:
        n = Decimal(value)
    except (TypeError, InvalidOperation):
        return value
    return f"${n:,.0f}"


@register.simple_tag
def filter_url(cat=None, q=None):
    """Build a ?cat=&q= querystring, dropping empty parts."""
    params = {}
    if cat and cat != "All":
        params["cat"] = cat
    if q:
        params["q"] = q
    return f"?{urlencode(params)}" if params else "?"
