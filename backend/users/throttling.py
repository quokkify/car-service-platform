"""Failed-login throttling shared by the API login and the Django admin login.

Two fixed-window counters are kept in Django's cache: one per client IP and one per account (normalized email).
Only failures count. A blocked request is answered with 429 before credentials are checked, so the window cannot
be used to probe passwords. Windows expire on their own; there is no permanent lockout.
"""

import hashlib
import time

from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.core.cache import cache
from django.dispatch import receiver
from django.http import HttpResponse
from django.urls import reverse

_KEY_PREFIX = "login_throttle"


def client_ip(request) -> str:
    header = settings.CLIENT_IP_HEADER
    if header:
        value = request.META.get("HTTP_" + header.upper().replace("-", "_"), "")
        hops = [hop.strip() for hop in value.split(",") if hop.strip()]
        if hops:
            return hops[-1]
    return request.META.get("REMOTE_ADDR", "")


def _account_key(account: str) -> str:
    digest = hashlib.sha256(account.strip().lower().encode()).hexdigest()
    return f"{_KEY_PREFIX}:account:{digest}"


def _ip_key(ip: str) -> str:
    return f"{_KEY_PREFIX}:ip:{ip}"


def _counters(request, account: str | None):
    yield _ip_key(client_ip(request)), settings.LOGIN_THROTTLE_IP_LIMIT, settings.LOGIN_THROTTLE_IP_WINDOW_SECONDS
    if account and account.strip():
        yield (
            _account_key(account),
            settings.LOGIN_THROTTLE_ACCOUNT_LIMIT,
            settings.LOGIN_THROTTLE_ACCOUNT_WINDOW_SECONDS,
        )


def _current_count(key: str, window: int, now: float) -> tuple[int, float]:
    count, started = cache.get(key, (0, now))
    if now - started >= window:
        return 0, now
    return count, started


def is_blocked(request, account: str | None) -> bool:
    now = time.time()
    return any(_current_count(key, window, now)[0] >= limit for key, limit, window in _counters(request, account))


def record_failure(request, account: str | None) -> None:
    now = time.time()
    for key, _limit, window in _counters(request, account):
        count, started = _current_count(key, window, now)
        cache.set(key, (count + 1, started), max(1, int(started + window - now) + 1))


def clear_account(account: str) -> None:
    cache.delete(_account_key(account))


def too_many_attempts_response() -> HttpResponse:
    return HttpResponse("Too many login attempts. Please try again later.", status=429, content_type="text/plain")


@receiver(user_login_failed, dispatch_uid="users.throttling.record_failure")
def _on_login_failed(sender, credentials, request=None, **kwargs):
    if request is None:
        return
    record_failure(request, credentials.get("email") or credentials.get("username"))


@receiver(user_logged_in, dispatch_uid="users.throttling.clear_account")
def _on_logged_in(sender, request, user, **kwargs):
    clear_account(user.get_username())


class AdminLoginThrottleMiddleware:
    """Refuse Django admin login POSTs while the client IP or the account is throttled."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and request.path == reverse("admin:login"):
            if is_blocked(request, request.POST.get("username")):
                return too_many_attempts_response()
        return self.get_response(request)
