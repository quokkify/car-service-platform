from django.conf import settings
from django.core.management.base import BaseCommand

from users.models import User

from ._seed import check_seed_password

DEV_ADMIN_EMAIL = "admin@autoservice.local"
DEV_ADMIN_PASSWORD = "admin12345"


class Command(BaseCommand):
    help = (
        "Create the initial admin user from ADMIN_EMAIL / ADMIN_PASSWORD if it does not exist yet. "
        "Existing accounts are never modified. Dev defaults apply only with DEBUG on."
    )

    def handle(self, *args, **options):
        email = (settings.ADMIN_EMAIL or "").strip().lower()
        password = (settings.ADMIN_PASSWORD or "").strip()

        if settings.DEBUG:
            email = email or DEV_ADMIN_EMAIL
            password = password or DEV_ADMIN_PASSWORD

        if not email or not password:
            self.stdout.write("No admin credentials configured; skipping seed_admin.")
            return

        if User.objects.filter(email__iexact=email).exists():
            self.stdout.write(f"Admin user {email} already exists; leaving it unchanged.")
            return

        check_seed_password(password, "ADMIN_PASSWORD")

        User.objects.create_superuser(email=email, password=password, role=User.Role.ADMIN)
        self.stdout.write(f"Created admin user: {email}")
