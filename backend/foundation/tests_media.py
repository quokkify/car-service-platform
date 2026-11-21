"""Regression guards: files under MEDIA_ROOT are served only to logged-in users, safely."""

import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

User = get_user_model()

PDF_BYTES = b"%PDF-1.4 customer export body"


class ProtectedMediaTests(TestCase):
    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)
        self.media_root = self.sandbox / "media"
        (self.media_root / "repair_exports" / "1").mkdir(parents=True)
        (self.media_root / "repair_exports" / "1" / "v1.pdf").write_bytes(PDF_BYTES)
        (self.sandbox / "secret.txt").write_bytes(b"outside-media-root")

        media_override = override_settings(MEDIA_ROOT=str(self.media_root))
        media_override.enable()
        self.addCleanup(media_override.disable)

        self.client = APIClient()
        self.staff = User.objects.create_user(email="staff@media.local", password="staffpass123", role="staff")
        self.admin = User.objects.create_user(
            email="admin@media.local", password="adminpass123", role="admin", is_staff=True
        )

    def _write(self, relative_path: str, content: bytes) -> None:
        target = self.media_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def test_anonymous_request_is_rejected_without_file_bytes(self):
        """Regression guard: anonymous visitors could download repair PDFs from /media/."""
        response = self.client.get("/media/repair_exports/1/v1.pdf")

        self.assertEqual(response.status_code, 403)
        body = b"".join(response.streaming_content) if response.streaming else response.content
        self.assertNotIn(PDF_BYTES, body)

    def test_anonymous_request_for_missing_file_is_rejected_before_lookup(self):
        """Regression guard: anonymous visitors must not learn which media paths exist."""
        response = self.client.get("/media/repair_exports/999/v1.pdf")

        self.assertEqual(response.status_code, 403)

    def test_staff_session_receives_file(self):
        """Regression guard: logged-in staff keep access to stored media (same-origin cookie)."""
        self.client.force_login(self.staff)

        response = self.client.get("/media/repair_exports/1/v1.pdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), PDF_BYTES)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertTrue(response["Content-Disposition"].startswith("inline"))

    def test_responses_are_never_cached(self):
        """Regression guard: a cached customer PDF could outlive logout on a shared workshop PC."""
        anonymous = self.client.get("/media/repair_exports/1/v1.pdf")
        self.client.force_login(self.staff)
        served = self.client.get("/media/repair_exports/1/v1.pdf")
        missing = self.client.get("/media/repair_exports/1/v99.pdf")

        for response in (anonymous, served, missing):
            with self.subTest(status=response.status_code):
                self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_admin_session_receives_file(self):
        """Regression guard: Django admin file links (RepairDocument inline, purchase invoice) still work."""
        self.client.force_login(self.admin)

        response = self.client.get("/media/repair_exports/1/v1.pdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), PDF_BYTES)

    def test_missing_file_returns_404_for_logged_in_user(self):
        self.client.force_login(self.staff)

        response = self.client.get("/media/repair_exports/1/v99.pdf")

        self.assertEqual(response.status_code, 404)

    def test_path_traversal_is_rejected(self):
        """Regression guard: the authenticated media view must not escape MEDIA_ROOT."""
        self.client.force_login(self.staff)

        for path in ("/media/../secret.txt", "/media/%2e%2e/secret.txt", "/media/repair_exports/../../secret.txt"):
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertIn(response.status_code, (400, 404))
                body = b"".join(response.streaming_content) if response.streaming else response.content
                self.assertNotIn(b"outside-media-root", body)

    def test_directory_listing_is_not_served(self):
        self.client.force_login(self.staff)

        response = self.client.get("/media/repair_exports/")

        self.assertEqual(response.status_code, 404)

    def test_active_content_is_forced_to_download(self):
        """Regression guard: uploaded HTML/SVG must not render in the app origin."""
        self._write("invoices/page.html", b"<script>alert(1)</script>")
        self._write("invoices/image.svg", b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>')
        self._write("invoices/notes.txt", b"plain text")
        self.client.force_login(self.staff)

        for path in ("/media/invoices/page.html", "/media/invoices/image.svg", "/media/invoices/notes.txt"):
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 200)
                self.assertTrue(response["Content-Disposition"].startswith("attachment"))
                self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_images_render_inline(self):
        self._write("invoices/scan.png", b"\x89PNG\r\n\x1a\nfake")
        self._write("invoices/scan.jpg", b"\xff\xd8\xff fake")
        self._write("invoices/scan.webp", b"RIFF fake WEBP")
        self.client.force_login(self.staff)

        for path in ("/media/invoices/scan.png", "/media/invoices/scan.jpg", "/media/invoices/scan.webp"):
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 200)
                self.assertTrue(response["Content-Disposition"].startswith("inline"))
                self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_uploaded_invoice_url_is_readable_only_when_logged_in(self):
        """Regression guard: the invoice upload API's returned URL is the frontend's /media/ consumer."""
        self.client.force_login(self.staff)
        upload = SimpleUploadedFile("invoice.pdf", PDF_BYTES, content_type="application/pdf")
        url = self.client.post("/api/uploads/invoice/", {"file": upload}, format="multipart").json()["url"]

        logged_in = self.client.get(url)
        self.assertEqual(logged_in.status_code, 200)
        self.assertEqual(b"".join(logged_in.streaming_content), PDF_BYTES)

        self.client.logout()
        anonymous = self.client.get(url)
        self.assertEqual(anonymous.status_code, 403)


class RepairExportPathTests(TestCase):
    def test_new_export_paths_are_not_guessable(self):
        """Regression guard: export paths were repair_exports/<id>/v<n>.pdf and trivially enumerable."""
        from repairs.models import RepairDocument, repair_pdf_upload_to

        doc = RepairDocument(repair_id=7, version=3)

        first = repair_pdf_upload_to(doc, "v3.pdf")
        second = repair_pdf_upload_to(doc, "v3.pdf")

        self.assertTrue(first.startswith("repair_exports/7/"))
        self.assertTrue(first.endswith(".pdf"))
        self.assertNotEqual(first, "repair_exports/7/v3.pdf")
        self.assertNotEqual(first, second)
