"""Regression guards: seed commands never overwrite existing accounts and refuse default passwords in production."""

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

User = get_user_model()

STRONG_PASSWORD = "vQ7#nT2!pLx9-rWm"


class SeedAdminRegressionTests(TestCase):
    def _run(self):
        out = StringIO()
        call_command("seed_admin", stdout=out, stderr=StringIO())
        return out.getvalue()

    @override_settings(DEBUG=False, ADMIN_EMAIL="owner@example.com", ADMIN_PASSWORD=STRONG_PASSWORD)
    def test_creates_admin_when_missing(self):
        self._run()

        admin = User.objects.get(email="owner@example.com")
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.check_password(STRONG_PASSWORD))

    @override_settings(DEBUG=False, ADMIN_EMAIL="owner@example.com", ADMIN_PASSWORD=STRONG_PASSWORD)
    def test_regression_does_not_reset_password_of_existing_admin(self):
        User.objects.create_superuser(email="owner@example.com", password="rotated-by-operator-123")

        output = self._run()

        admin = User.objects.get(email="owner@example.com")
        self.assertTrue(admin.check_password("rotated-by-operator-123"))
        self.assertIn("already exists", output)

    @override_settings(DEBUG=False, ADMIN_EMAIL="Owner@Example.com", ADMIN_PASSWORD=STRONG_PASSWORD)
    def test_regression_does_not_reactivate_deactivated_admin(self):
        admin = User.objects.create_superuser(email="owner@example.com", password="rotated-by-operator-123")
        admin.is_active = False
        admin.save(update_fields=["is_active"])

        self._run()

        admin.refresh_from_db()
        self.assertFalse(admin.is_active)

    @override_settings(DEBUG=False, ADMIN_EMAIL="owner@example.com", ADMIN_PASSWORD="admin12345")
    def test_regression_refuses_known_default_password_when_debug_off(self):
        with self.assertRaisesMessage(CommandError, "ADMIN_PASSWORD"):
            self._run()

        self.assertFalse(User.objects.filter(email="owner@example.com").exists())

    @override_settings(DEBUG=False, ADMIN_EMAIL="owner@example.com", ADMIN_PASSWORD="short")
    def test_refuses_weak_password_when_debug_off(self):
        with self.assertRaisesMessage(CommandError, "ADMIN_PASSWORD"):
            self._run()

    @override_settings(DEBUG=False, ADMIN_EMAIL="", ADMIN_PASSWORD="")
    def test_regression_no_default_admin_when_debug_off(self):
        output = self._run()

        self.assertFalse(User.objects.exists())
        self.assertIn("skipping", output)

    @override_settings(DEBUG=False, ADMIN_EMAIL="owner@example.com", ADMIN_PASSWORD="")
    def test_skips_without_password_when_debug_off(self):
        self._run()

        self.assertFalse(User.objects.exists())

    @override_settings(DEBUG=True, ADMIN_EMAIL="", ADMIN_PASSWORD="")
    def test_debug_creates_dev_admin(self):
        self._run()

        admin = User.objects.get(email="admin@autoservice.local")
        self.assertTrue(admin.check_password("admin12345"))


class SeedStaffRegressionTests(TestCase):
    def _run(self):
        out = StringIO()
        call_command("seed_staff", stdout=out, stderr=StringIO())
        return out.getvalue()

    @override_settings(DEBUG=False, STAFF_EMAIL="master@example.com", STAFF_PASSWORD=STRONG_PASSWORD)
    def test_regression_does_not_reset_or_reactivate_existing_staff(self):
        staff = User.objects.create_user(email="master@example.com", password="own-password-123", role="staff")
        staff.is_active = False
        staff.save(update_fields=["is_active"])

        self._run()

        staff.refresh_from_db()
        self.assertTrue(staff.check_password("own-password-123"))
        self.assertFalse(staff.is_active)

    @override_settings(DEBUG=False, STAFF_EMAIL="master@example.com", STAFF_PASSWORD="staff12345")
    def test_regression_refuses_known_default_password_when_debug_off(self):
        with self.assertRaisesMessage(CommandError, "STAFF_PASSWORD"):
            self._run()

    @override_settings(DEBUG=True, STAFF_EMAIL="", STAFF_PASSWORD="")
    def test_debug_creates_dev_staff(self):
        self._run()

        staff = User.objects.get(email="staff@autoservice.local")
        self.assertTrue(staff.check_password("staff12345"))
        self.assertEqual(staff.role, User.Role.STAFF)
