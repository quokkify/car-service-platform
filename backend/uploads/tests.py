import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

User = get_user_model()

UPLOAD_URL = "/api/uploads/invoice/"


def make_pdf(name="invoice.pdf", size=1024):
    return SimpleUploadedFile(name, b"%PDF-1.4 " + b"x" * size, content_type="application/pdf")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class InvoiceUploadTests(TestCase):
    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=False)
        self.admin_password = "adminpass123"
        self.staff_password = "staffpass123"
        self.admin = User.objects.create_user(
            email="admin@upload.local",
            password=self.admin_password,
            role="admin",
            is_staff=True,
        )
        self.staff = User.objects.create_user(
            email="staff@upload.local",
            password=self.staff_password,
            role="staff",
        )

    def _login(self, user, password):
        self.client.post(
            "/api/auth/login",
            {"email": user.email, "password": password},
            format="json",
        )

    def test_admin_can_upload_valid_pdf(self):
        self._login(self.admin, self.admin_password)

        response = self.client.post(UPLOAD_URL, {"file": make_pdf()}, format="multipart")

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("url", data)
        self.assertIn("name", data)
        self.assertIn("/media/invoices/", data["url"])

    def test_staff_can_upload_valid_pdf(self):
        self._login(self.staff, self.staff_password)

        response = self.client.post(UPLOAD_URL, {"file": make_pdf()}, format="multipart")

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn("url", data)
        self.assertIn("name", data)

    def test_staff_can_upload_plain_text_invoice(self):
        self._login(self.staff, self.staff_password)
        txt = SimpleUploadedFile(
            "invoice.txt",
            b"Supplier: Demo\nLine 1\n",
            content_type="text/plain",
        )

        response = self.client.post(UPLOAD_URL, {"file": txt}, format="multipart")

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["name"], "invoice.txt")
        self.assertIn("/media/invoices/", data["url"])

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.post(UPLOAD_URL, {"file": make_pdf()}, format="multipart")

        self.assertIn(response.status_code, [401, 403])

    def test_missing_file_returns_400(self):
        self._login(self.admin, self.admin_password)

        response = self.client.post(UPLOAD_URL, {}, format="multipart")

        self.assertEqual(response.status_code, 400)
        self.assertIn("detail", response.json())

    def test_disallowed_extension_returns_400(self):
        self._login(self.admin, self.admin_password)
        exe_file = SimpleUploadedFile("payload.exe", b"MZ\x90\x00", content_type="application/octet-stream")

        response = self.client.post(UPLOAD_URL, {"file": exe_file}, format="multipart")

        self.assertEqual(response.status_code, 400)
        self.assertIn("detail", response.json())

    def test_oversized_file_returns_400(self):
        self._login(self.admin, self.admin_password)
        oversized = SimpleUploadedFile(
            "big.pdf",
            b"%PDF-1.4 " + b"x" * (10 * 1024 * 1024 + 1),
            content_type="application/pdf",
        )

        response = self.client.post(UPLOAD_URL, {"file": oversized}, format="multipart")

        self.assertEqual(response.status_code, 400)
        self.assertIn("detail", response.json())

    # Regression guard: active content (HTML/SVG/XML) must never be stored under /media/ — it would be
    # served back from the backend origin and could run script in a signed-in admin's session.
    def test_active_content_extensions_are_rejected(self):
        self._login(self.staff, self.staff_password)
        cases = [
            ("invoice.html", b"<html><body>invoice</body></html>", "text/html"),
            ("invoice.htm", b"<html><body>invoice</body></html>", "text/html"),
            ("invoice.svg", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "image/svg+xml"),
            ("invoice.xhtml", b"<html xmlns='http://www.w3.org/1999/xhtml'></html>", "application/xhtml+xml"),
            ("invoice.xml", b"<?xml version='1.0'?><invoice/>", "application/xml"),
        ]
        for name, body, content_type in cases:
            with self.subTest(name=name):
                upload = SimpleUploadedFile(name, body, content_type=content_type)

                response = self.client.post(UPLOAD_URL, {"file": upload}, format="multipart")

                self.assertEqual(response.status_code, 400)
                self.assertIn("detail", response.json())

    # Regression guard: the extension alone is not trusted — content must match the declared type.
    def test_content_not_matching_extension_is_rejected(self):
        self._login(self.staff, self.staff_password)
        markup = b"<html><body>not an invoice</body></html>"
        for name in ("invoice.pdf", "invoice.png", "invoice.jpg", "invoice.webp", "invoice.tiff", "invoice.docx", "invoice.xls"):
            with self.subTest(name=name):
                upload = SimpleUploadedFile(name, markup, content_type="application/octet-stream")

                response = self.client.post(UPLOAD_URL, {"file": upload}, format="multipart")

                self.assertEqual(response.status_code, 400)
                self.assertIn("detail", response.json())

    # Regression guard: a .txt upload whose content is markup is refused (browsers may sniff it as HTML).
    def test_text_upload_with_markup_is_rejected(self):
        self._login(self.staff, self.staff_password)
        for body in (b"<html><body>x</body></html>", b"\xef\xbb\xbf  \n<!DOCTYPE html><p>x", b"<svg><text>x</text></svg>"):
            with self.subTest(body=body[:20]):
                upload = SimpleUploadedFile("invoice.txt", body, content_type="text/plain")

                response = self.client.post(UPLOAD_URL, {"file": upload}, format="multipart")

                self.assertEqual(response.status_code, 400)

    def test_legitimate_invoice_types_are_accepted(self):
        self._login(self.staff, self.staff_password)
        cases = [
            ("invoice.pdf", b"%PDF-1.7\n" + b"x" * 64),
            ("scan.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64),
            ("scan.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 64),
            ("scan.jpeg", b"\xff\xd8\xff\xe1" + b"\x00" * 64),
            ("scan.webp", b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 64),
            ("scan.tif", b"II*\x00" + b"\x00" * 64),
            ("scan.tiff", b"MM\x00*" + b"\x00" * 64),
            ("invoice.txt", "Sprzedawca: Demo — faktura 1 < 2 & ok\n".encode("utf-8")),
            ("invoice.text", b"Line 1\nLine 2\n"),
            ("invoice.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64),
            ("invoice.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64),
            ("invoice.docx", b"PK\x03\x04" + b"\x00" * 64),
            ("invoice.xlsx", b"PK\x03\x04" + b"\x00" * 64),
        ]
        for name, body in cases:
            with self.subTest(name=name):
                upload = SimpleUploadedFile(name, body, content_type="application/octet-stream")

                response = self.client.post(UPLOAD_URL, {"file": upload}, format="multipart")

                self.assertEqual(response.status_code, 201, response.content)
                self.assertTrue(response.json()["url"].endswith(name.rsplit(".", 1)[1].lower()))
