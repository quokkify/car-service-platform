from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError

from config.security import KNOWN_DEFAULT_PASSWORDS


def check_seed_password(password: str, env_name: str) -> None:
    """Refuse template/default or weak passwords outside DEBUG."""
    if settings.DEBUG:
        return
    if password.lower() in KNOWN_DEFAULT_PASSWORDS:
        raise CommandError(f"{env_name} is a known default password; set a unique strong password.")
    try:
        validate_password(password)
    except ValidationError as exc:
        raise CommandError(f"{env_name} is too weak: {' '.join(exc.messages)}") from exc


def refuse_existing_default_password(user, default_password: str) -> None:
    """Outside DEBUG, stop if an account seeded by an earlier version still has the old default password."""
    if settings.DEBUG or not user.check_password(default_password):
        return
    raise CommandError(
        f"Account {user.email} still uses the default password from an earlier seed. Rotate it before starting: "
        f"python manage.py changepassword {user.email}"
    )
