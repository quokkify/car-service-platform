"""Failed-login throttling shared by the API login and the Django admin login.

Fixed-window counters are kept in Django's cache: one per client IP and one per account (normalized email).
Only failures count. A blocked request is answered with 429 before credentials are checked, so the window cannot
be used to probe passwords. Windows expire on their own; there is no permanent lockout.

The account limit stops guessing spread over many IPs. So that someone failing against an account cannot lock its
owner out, an IP that has signed in to the account successfully before ("known source") is exempt from the account
limit (it still has the per-IP limit). An attacker gains nothing from that exemption unless they control an address
the owner signed in from.

Counters use the window number in the key and cache.add + cache.incr, which is atomic on LocMem and Redis. The
database cache implements incr as get + set, so concurrent failures there can undercount by a few attempts.
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


def _account_digest(account: str) -> str:
    return hashlib.sha256(account.strip().lower().encode()).hexdigest()


def _window_key(scope: str, window: int, now: float) -> str:
    return f"{_KEY_PREFIX}:{scope}:{int(now // window)}"


def _ip_counter(request, now: float) -> tuple[str, int, int]:
    window = settings.LOGIN_THROTTLE_IP_WINDOW_SECONDS
    return _window_key(f"ip:{client_ip(request)}", window, now), settings.LOGIN_THROTTLE_IP_LIMIT, window


def _account_counter(account: str, now: float) -> tuple[str, int, int]:
    window = settings.LOGIN_THROTTLE_ACCOUNT_WINDOW_SECONDS
    return _window_key(f"account:{_account_digest(account)}", window, now), settings.LOGIN_THROTTLE_ACCOUNT_LIMIT, window


def _known_source_key(account: str, ip: str) -> str:
    return f"{_KEY_PREFIX}:known:{_account_digest(account)}:{ip}"


def _has_account(account: str | None) -> bool:
    return bool(account and account.strip())


def is_blocked(request, account: str | None) -> bool:
    now = time.time()
    key, limit, _window = _ip_counter(request, now)
    if cache.get(key, 0) >= limit:
        return True
    if not _has_account(account):
        return False
    key, limit, _window = _account_counter(account, now)
    if cache.get(key, 0) < limit:
        return False
    return not cache.get(_known_source_key(account, client_ip(request)), False)


def record_failure(request, account: str | None) -> None:
    now = time.time()
    counters = [_ip_counter(request, now)]
    if _has_account(account):
        counters.append(_account_counter(account, now))
    for key, _limit, window in counters:
        cache.add(key, 0, window)
        try:
            cache.incr(key)
        except ValueError:
            # Expired between add and incr (window boundary): start the counter again.
            cache.add(key, 1, window)
        cache.touch(key, window)


def record_success(request, account: str) -> None:
    now = time.time()
    cache.delete(_account_counter(account, now)[0])
    cache.set(
        _known_source_key(account, client_ip(request)),
        True,
        settings.LOGIN_THROTTLE_KNOWN_SOURCE_SECONDS,
    )


def too_many_attempts_response() -> HttpResponse:
    return HttpResponse("Too many login attempts. Please try again later.", status=429, content_type="text/plain")


@receiver(user_login_failed, dispatch_uid="users.throttling.record_failure")
def _on_login_failed(sender, credentials, request=None, **kwargs):
    if request is None:
        return
    record_failure(request, credentials.get("email") or credentials.get("username"))


@receiver(user_logged_in, dispatch_uid="users.throttling.record_success")
def _on_logged_in(sender, request, user, **kwargs):
    if request is None:
        return
    record_success(request, user.get_username())


class AdminLoginThrottleMiddleware:
    """Refuse Django admin login POSTs while the client IP or the account is throttled."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and request.path == reverse("admin:login"):
            if is_blocked(request, request.POST.get("username")):
                return too_many_attempts_response()
        return self.get_response(request)
