"""Regression guards for login throttling (API login and Django admin login)."""

import threading
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.test.client import RequestFactory
from rest_framework.test import APIClient

from users import throttling

User = get_user_model()

THROTTLE_SETTINGS = {
    "LOGIN_THROTTLE_IP_LIMIT": 10,
    "LOGIN_THROTTLE_IP_WINDOW_SECONDS": 60,
    "LOGIN_THROTTLE_ACCOUNT_LIMIT": 5,
    "LOGIN_THROTTLE_ACCOUNT_WINDOW_SECONDS": 900,
    "CLIENT_IP_HEADER": "X-Real-IP",
}


@override_settings(**THROTTLE_SETTINGS)
class LoginThrottleRegressionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient(enforce_csrf_checks=False)
        self.user = User.objects.create_user(email="victim@test.local", password="correctpass123", role="staff")

    def tearDown(self):
        cache.clear()

    def _login(self, email=None, password="wrongpassword", **headers):
        return self.client.post(
            "/api/auth/login",
            {"email": email or self.user.email, "password": password},
            format="json",
            **headers,
        )

    def test_regression_spoofed_forwarded_for_does_not_reset_ip_counter(self):
        for attempt in range(10):
            response = self._login(
                email=f"nobody{attempt}@test.local",
                HTTP_X_REAL_IP="203.0.113.7",
                HTTP_X_FORWARDED_FOR=f"198.51.100.{attempt}",
            )
            self.assertEqual(response.status_code, 401)

        response = self._login(
            email="nobody-else@test.local",
            HTTP_X_REAL_IP="203.0.113.7",
            HTTP_X_FORWARDED_FOR="198.51.100.250",
        )
        self.assertEqual(response.status_code, 429)

    def test_regression_ip_taken_from_last_hop_of_configured_header(self):
        with self.settings(CLIENT_IP_HEADER="X-Forwarded-For"):
            for attempt in range(10):
                response = self._login(
                    email=f"nobody{attempt}@test.local",
                    HTTP_X_FORWARDED_FOR=f"198.51.100.{attempt}, 203.0.113.7",
                )
                self.assertEqual(response.status_code, 401)

            response = self._login(email="nobody-else@test.local", HTTP_X_FORWARDED_FOR="198.51.100.99, 203.0.113.7")
            self.assertEqual(response.status_code, 429)

    def test_regression_account_throttle_triggers_across_different_ips(self):
        for attempt in range(5):
            response = self._login(HTTP_X_REAL_IP=f"198.51.100.{attempt}")
            self.assertEqual(response.status_code, 401)

        response = self._login(password="correctpass123", HTTP_X_REAL_IP="203.0.113.200")
        self.assertEqual(response.status_code, 429)

    def test_regression_account_throttle_is_case_insensitive(self):
        for attempt in range(5):
            self._login(email=self.user.email.upper(), HTTP_X_REAL_IP=f"198.51.100.{attempt}")

        response = self._login(password="correctpass123", HTTP_X_REAL_IP="203.0.113.200")
        self.assertEqual(response.status_code, 429)

    def test_regression_account_throttle_expires_after_window(self):
        clock = mock.Mock(return_value=1_000_000.0)
        with mock.patch("users.throttling.time.time", clock):
            for attempt in range(5):
                self._login(HTTP_X_REAL_IP=f"198.51.100.{attempt}")
            self.assertEqual(self._login(password="correctpass123", HTTP_X_REAL_IP="203.0.113.200").status_code, 429)

            clock.return_value += 901
            response = self._login(password="correctpass123", HTTP_X_REAL_IP="203.0.113.200")

        self.assertEqual(response.status_code, 200)

    def test_regression_owner_from_known_ip_is_not_locked_out_by_failures_elsewhere(self):
        self.assertEqual(self._login(password="correctpass123", HTTP_X_REAL_IP="192.0.2.10").status_code, 200)
        self.client.post("/api/auth/logout")
        for attempt in range(5):
            self._login(HTTP_X_REAL_IP=f"198.51.100.{attempt}")

        stranger = self._login(password="correctpass123", HTTP_X_REAL_IP="203.0.113.200")
        owner = self._login(password="correctpass123", HTTP_X_REAL_IP="192.0.2.10")

        self.assertEqual(owner.status_code, 200)
        self.assertEqual(stranger.status_code, 429)

    def test_regression_concurrent_failures_are_all_counted(self):
        request = RequestFactory().post("/api/auth/login", HTTP_X_REAL_IP="203.0.113.50")
        workers = [threading.Thread(target=throttling.record_failure, args=(request, None)) for _ in range(50)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        key, _limit, _window = throttling._ip_counter(request, throttling.time.time())
        self.assertEqual(cache.get(key), 50)

    def test_account_throttle_does_not_affect_other_accounts(self):
        other = User.objects.create_user(email="other@test.local", password="otherpass123", role="staff")
        for attempt in range(5):
            self._login(HTTP_X_REAL_IP=f"198.51.100.{attempt}")

        response = self._login(email=other.email, password="otherpass123", HTTP_X_REAL_IP="203.0.113.200")
        self.assertEqual(response.status_code, 200)


@override_settings(**THROTTLE_SETTINGS)
class AdminLoginThrottleRegressionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser(email="root@test.local", password="adminpass123")

    def tearDown(self):
        cache.clear()

    def _admin_login(self, password, ip):
        return self.client.post(
            "/admin/login/?next=/admin/",
            {"username": self.admin.email, "password": password},
            HTTP_X_REAL_IP=ip,
        )

    def test_regression_admin_login_is_throttled_per_account(self):
        for attempt in range(5):
            response = self._admin_login("wrongpassword", f"198.51.100.{attempt}")
            self.assertEqual(response.status_code, 200)

        response = self._admin_login("adminpass123", "203.0.113.200")

        self.assertEqual(response.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_regression_admin_login_shares_ip_counter_with_api(self):
        api = APIClient(enforce_csrf_checks=False)
        for attempt in range(10):
            api.post(
                "/api/auth/login",
                {"email": f"nobody{attempt}@test.local", "password": "x"},
                format="json",
                HTTP_X_REAL_IP="203.0.113.7",
            )

        response = self._admin_login("adminpass123", "203.0.113.7")

        self.assertEqual(response.status_code, 429)

    def test_admin_login_succeeds_below_limit(self):
        response = self._admin_login("adminpass123", "203.0.113.8")

        self.assertEqual(response.status_code, 302)
