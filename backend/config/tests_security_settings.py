"""Regression guards: production settings must fail closed on weak secrets."""

import runpy
import secrets

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.security import validate_secret_key

STRONG_KEY = secrets.token_urlsafe(50)


def _load_settings(monkeypatch, **env):
    for name in ("DJANGO_SECRET_KEY", "DJANGO_DEBUG", "SENTRY_DSN"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return runpy.run_module("config.settings", run_name="config.settings")


@pytest.mark.parametrize(
    "key",
    [
        "",
        "change-me",
        "change-me-in-production",
        "django-insecure-dev-only-change-me",
        "short-but-random-Q2x9",
        "change-me" + "x" * 60,
    ],
)
def test_regression_settings_refuse_weak_secret_key_when_debug_off(monkeypatch, key):
    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
        _load_settings(monkeypatch, DJANGO_SECRET_KEY=key, DJANGO_DEBUG="False")


def test_regression_settings_refuse_missing_secret_key_by_default(monkeypatch):
    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
        _load_settings(monkeypatch)


def test_settings_accept_strong_secret_key_when_debug_off(monkeypatch):
    loaded = _load_settings(monkeypatch, DJANGO_SECRET_KEY=STRONG_KEY, DJANGO_DEBUG="False")

    assert loaded["DEBUG"] is False
    assert loaded["SECRET_KEY"] == STRONG_KEY


def test_settings_debug_defaults_to_false(monkeypatch):
    loaded = _load_settings(monkeypatch, DJANGO_SECRET_KEY=STRONG_KEY)

    assert loaded["DEBUG"] is False


def test_settings_allow_dev_key_when_debug_on(monkeypatch):
    loaded = _load_settings(monkeypatch, DJANGO_SECRET_KEY="dev-only-insecure-key", DJANGO_DEBUG="True")

    assert loaded["DEBUG"] is True
    assert loaded["SECRET_KEY"] == "dev-only-insecure-key"


def test_validate_secret_key_error_is_actionable():
    with pytest.raises(ImproperlyConfigured) as excinfo:
        validate_secret_key("change-me", debug=False)

    message = str(excinfo.value)
    assert "at least 50" in message
    assert "secrets.token_urlsafe(50)" in message
