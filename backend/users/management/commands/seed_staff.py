from django.conf import settings
from django.core.management.base import BaseCommand

from users.models import User

from ._seed import check_seed_password, refuse_existing_default_password

DEV_STAFF_EMAIL = "staff@autoservice.local"
DEV_STAFF_PASSWORD = "staff12345"


class Command(BaseCommand):
    help = (
        "Create the initial staff user from STAFF_EMAIL / STAFF_PASSWORD if it does not exist yet. "
        "Existing accounts are never modified. Dev defaults apply only with DEBUG on."
    )

    def handle(self, *args, **options):
        email = (settings.STAFF_EMAIL or "").strip().lower()
        password = (settings.STAFF_PASSWORD or "").strip()

        if settings.DEBUG:
            email = email or DEV_STAFF_EMAIL
            password = password or DEV_STAFF_PASSWORD
        else:
            for candidate in {email, DEV_STAFF_EMAIL} - {""}:
                seeded = User.objects.filter(email__iexact=candidate).first()
                if seeded is not None:
                    refuse_existing_default_password(seeded, DEV_STAFF_PASSWORD)

        if not email or not password:
            self.stdout.write("No staff credentials configured; skipping seed_staff.")
            return

        if User.objects.filter(email__iexact=email).exists():
            self.stdout.write(f"Staff user {email} already exists; leaving it unchanged.")
            return

        check_seed_password(password, "STAFF_PASSWORD")

        User.objects.create_user(
            email=email,
            password=password,
            first_name="Ivan",
            last_name="Master",
            role=User.Role.STAFF,
        )
        self.stdout.write(f"Created staff user: {email}")
