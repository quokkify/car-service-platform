from django.core.exceptions import ImproperlyConfigured

MIN_SECRET_KEY_LENGTH = 50
# Substrings of the placeholder keys shipped in templates, docs and older compose defaults.
SECRET_KEY_PLACEHOLDER_MARKERS = (
    "change-me",
    "changeme",
    "django-insecure",
    "insecure",
    "placeholder",
    "replace-me",
    "your-secret",
)
# Passwords that have appeared in templates, docs or seed defaults; never acceptable outside DEBUG.
KNOWN_DEFAULT_PASSWORDS = frozenset(
    {
        "admin",
        "admin12345",
        "staff12345",
        "password",
        "change-me",
        "changeme",
        "change-me-in-production",
    }
)


def validate_secret_key(key: str, debug: bool) -> None:
    if debug:
        return
    lowered = key.lower()
    problems = []
    if not key:
        problems.append("it is not set")
    elif len(key) < MIN_SECRET_KEY_LENGTH:
        problems.append(f"it is {len(key)} characters long")
    if any(marker in lowered for marker in SECRET_KEY_PLACEHOLDER_MARKERS):
        problems.append("it contains a placeholder value")
    if problems:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY is unsafe while DJANGO_DEBUG is off ("
            + "; ".join(problems)
            + f"). Set a random value of at least {MIN_SECRET_KEY_LENGTH} characters, e.g. the output of "
            '`python -c "import secrets; print(secrets.token_urlsafe(50))"`. '
            "For local development only, set DJANGO_DEBUG=True instead."
        )
