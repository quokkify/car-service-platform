import base64
import http.server
import io
import os
import shutil
import tempfile
import threading
import time
import unittest

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image
from pypdf import PdfReader
from rest_framework.test import APIClient

from customers.models import Customer
from vehicles.models import Vehicle

from .invoice_line_parse import extract_text_from_file
from .models import InvoiceLineParseTemplate, Purchase, Supplier, SupplierAlias, UnitOfMeasure


class SupplierApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            email="manager@test.local",
            password="manager12345",
            role="staff",
        )

    def test_list_suppliers(self):
        self.client.force_authenticate(self.user)
        Supplier.objects.create(name="AutoParts Ltd")
        Supplier.objects.create(name="SpeedSupply Co")

        response = self.client.get("/api/purchases/suppliers/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)

    def test_create_supplier(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/api/purchases/suppliers/",
            {
                "name": "TopGear Parts",
                "nip": "1234567890",
                "phone": "+48 600 100 200",
                "registered_address": "ul. Prosta 1, 00-001 Warszawa",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["name"], "TopGear Parts")
        self.assertEqual(data["nip"], "1234567890")
        self.assertEqual(data["phone"], "+48 600 100 200")
        self.assertEqual(data["registered_address"], "ul. Prosta 1, 00-001 Warszawa")

    def test_detail_supplier(self):
        self.client.force_authenticate(self.user)
        supplier = Supplier.objects.create(
            name="Detail Supplier",
            nip="9876543210",
            registered_address="ul. Testowa 5, Krakow",
        )

        response = self.client.get(f"/api/purchases/suppliers/{supplier.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Detail Supplier")
        self.assertEqual(response.json()["nip"], "9876543210")
        self.assertEqual(response.json()["registered_address"], "ul. Testowa 5, Krakow")

    def test_update_supplier(self):
        self.client.force_authenticate(self.user)
        supplier = Supplier.objects.create(name="Old Supplier", nip="111")

        response = self.client.patch(
            f"/api/purchases/suppliers/{supplier.id}",
            {
                "name": "Updated Supplier",
                "phone": "+48 600 222 333",
                "registered_address": "Updated address 10",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Updated Supplier")
        self.assertEqual(response.json()["phone"], "+48 600 222 333")
        self.assertEqual(response.json()["registered_address"], "Updated address 10")
        supplier.refresh_from_db()
        self.assertEqual(supplier.name, "Updated Supplier")
        self.assertEqual(supplier.registered_address, "Updated address 10")

    def test_search_suppliers_by_name(self):
        self.client.force_authenticate(self.user)
        Supplier.objects.create(name="AutoParts Ltd")
        Supplier.objects.create(name="SpeedSupply Co")

        response = self.client.get("/api/purchases/suppliers/", {"q": "auto"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "AutoParts Ltd")

    def test_create_supplier_alias(self):
        self.client.force_authenticate(self.user)
        supplier = Supplier.objects.create(name="Canonical Vendor", nip="")
        response = self.client.post(
            f"/api/purchases/suppliers/{supplier.id}/aliases/",
            {"alias_text": "  OCR Vendor Name  "},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["alias_text"], "OCR Vendor Name")
        self.assertEqual(data["normalized_key"], "ocr vendor name")
        alias = SupplierAlias.objects.get(pk=data["id"])
        self.assertEqual(alias.supplier_id, supplier.id)

    def test_duplicate_supplier_alias_returns_400(self):
        self.client.force_authenticate(self.user)
        supplier = Supplier.objects.create(name="Vendor A", nip="")
        Supplier.objects.create(name="Vendor B", nip="")
        SupplierAlias.objects.create(supplier=supplier, alias_text="shared token")
        other = Supplier.objects.get(name="Vendor B")
        response = self.client.post(
            f"/api/purchases/suppliers/{other.id}/aliases/",
            {"alias_text": "SHARED   token"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)


class PurchaseApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            email="manager@test.local",
            password="manager12345",
            role="staff",
        )
        self.supplier = Supplier.objects.create(name="Existing Supplier", nip="1111111111")
        self.customer = Customer.objects.create(
            full_name="Jan Kowalski",
            phone="+48 555 000 111",
            assigned_to=self.user,
        )
        self.vehicle = Vehicle.objects.create(
            customer=self.customer,
            license_plate="WA 12345",
            make="Ford",
            model="Focus",
        )
        self.uom_pcs = UnitOfMeasure.objects.get(code="pcs")
        self.uom_liters, _ = UnitOfMeasure.objects.get_or_create(code="L", defaults={"name": "Liters"})

    def _purchase_payload(self, **overrides):
        payload = {
            "order_date": "2026-03-20",
            "part_name": "Brake Disc",
            "quantity": 2,
            "purchase_price": "89.99",
            "supplier_name": self.supplier.name,
        }
        payload.update(overrides)
        return payload

    def test_authentication_is_required(self):
        response = self.client.get("/api/purchases/")
        self.assertEqual(response.status_code, 403)

    def test_list_purchases(self):
        self.client.force_authenticate(self.user)
        Purchase.objects.create(
            order_date="2026-03-20",
            part_name="Air Filter",
            quantity=1,
            purchase_price="15.00",
            supplier=self.supplier,
            unit_of_measure=self.uom_pcs,
        )

        response = self.client.get("/api/purchases/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)

    def test_create_purchase_with_new_supplier_name_auto_creates_supplier(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/api/purchases/",
            self._purchase_payload(supplier_name="Brand New Supplier"),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(Supplier.objects.filter(name="Brand New Supplier").exists())
        self.assertEqual(response.json()["supplier"]["name"], "Brand New Supplier")

    def test_create_purchase_with_existing_supplier_name_reuses_supplier(self):
        self.client.force_authenticate(self.user)
        supplier_count_before = Supplier.objects.count()

        response = self.client.post(
            "/api/purchases/",
            self._purchase_payload(supplier_name=self.supplier.name),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Supplier.objects.count(), supplier_count_before)
        self.assertEqual(response.json()["supplier"]["name"], self.supplier.name)

    def test_create_purchase_allows_fractional_quantity_for_liters(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/api/purchases/",
            self._purchase_payload(quantity="0.50", unit_of_measure_id=self.uom_liters.id),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["quantity"], 0.5)
        purchase = Purchase.objects.get(id=response.json()["id"])
        self.assertEqual(str(purchase.quantity), "0.50")

    def test_create_purchase_rejects_fractional_quantity_for_pcs(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/api/purchases/",
            self._purchase_payload(quantity="0.50", unit_of_measure_id=self.uom_pcs.id),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["quantity"][0], "This unit only allows whole quantities.")

    def test_bulk_create_purchases_shared_invoice(self):
        self.client.force_authenticate(self.user)
        supplier_count_before = Supplier.objects.count()

        response = self.client.post(
            "/api/purchases/bulk/",
            {
                "order_date": "2026-04-01",
                "supplier_name": "Bulk Supplier",
                "invoice_name": "inv.pdf",
                "invoice_url": "https://example.com/inv.pdf",
                "delivered": True,
                "is_shop_consumable": False,
                "lines": [
                    {
                        "part_name": "Part A",
                        "quantity": 2,
                        "purchase_price": "10.00",
                        "sale_price": "15.00",
                        "vehicle_id": self.vehicle.id,
                        "repair_code": "TOR-1001",
                    },
                    {
                        "part_name": "Part B",
                        "quantity": 1,
                        "purchase_price": "5.50",
                        "sale_price": "8.00",
                    },
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["part_name"], "Part A")
        self.assertEqual(data[1]["part_name"], "Part B")
        self.assertEqual(data[0]["invoice_name"], "inv.pdf")
        self.assertEqual(data[1]["invoice_name"], "inv.pdf")
        self.assertTrue(data[0]["delivered"])
        self.assertEqual(Supplier.objects.filter(name="Bulk Supplier").count(), 1)
        self.assertEqual(Supplier.objects.count(), supplier_count_before + 1)

    def test_bulk_create_sets_nip_on_new_supplier(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/purchases/bulk/",
            {
                "order_date": "2026-04-03",
                "supplier_name": "Fresh Vendor With Nip",
                "supplier_nip": "5251112233",
                "is_shop_consumable": True,
                "lines": [{"part_name": "Oil", "quantity": 1, "purchase_price": "20.00"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        vendor = Supplier.objects.get(name="Fresh Vendor With Nip")
        self.assertEqual(vendor.nip, "5251112233")

    def test_bulk_create_does_not_overwrite_existing_supplier_nip(self):
        self.client.force_authenticate(self.user)
        Supplier.objects.create(name="Locked Nip Vendor", nip="1111111111")
        response = self.client.post(
            "/api/purchases/bulk/",
            {
                "order_date": "2026-04-04",
                "supplier_name": "Locked Nip Vendor",
                "supplier_nip": "9999999999",
                "is_shop_consumable": True,
                "lines": [{"part_name": "Oil", "quantity": 1, "purchase_price": "10.00"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        vendor = Supplier.objects.get(name="Locked Nip Vendor")
        self.assertEqual(vendor.nip, "1111111111")

    def test_bulk_create_shop_consumables_rejects_vehicle(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/purchases/bulk/",
            {
                "order_date": "2026-04-02",
                "supplier_name": "Chem Co",
                "is_shop_consumable": True,
                "lines": [
                    {
                        "part_name": "Gloves",
                        "quantity": 5,
                        "purchase_price": "1.00",
                        "vehicle_id": self.vehicle.id,
                    },
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_bulk_create_allows_fractional_quantity_for_non_pcs_units(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/api/purchases/bulk/",
            {
                "order_date": "2026-04-01",
                "supplier_name": "Bulk Supplier",
                "lines": [
                    {
                        "part_name": "Coolant",
                        "quantity": "0.50",
                        "purchase_price": "10.00",
                        "sale_price": "15.00",
                        "unit_of_measure_id": self.uom_liters.id,
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()[0]["quantity"], 0.5)

    def test_bulk_create_rejects_fractional_quantity_for_pcs(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/api/purchases/bulk/",
            {
                "order_date": "2026-04-01",
                "supplier_name": "Bulk Supplier",
                "lines": [
                    {
                        "part_name": "Brake Disc",
                        "quantity": "0.50",
                        "purchase_price": "10.00",
                        "sale_price": "15.00",
                        "unit_of_measure_id": self.uom_pcs.id,
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        # DRF >= 3.18 reports many=True errors as a dict keyed by line index (encode/django-rest-framework#9837).
        self.assertEqual(response.json()["lines"]["0"]["quantity"][0], "This unit only allows whole quantities.")

    def test_bulk_create_shop_consumables_starts_not_inventoried(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/api/purchases/bulk/",
            {
                "order_date": "2026-04-02",
                "supplier_name": "Chem Co",
                "is_shop_consumable": True,
                "lines": [
                    {
                        "part_name": "Gloves",
                        "quantity": 5,
                        "purchase_price": "1.00",
                    },
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()[0]["current_stock_quantity"])
        self.assertIsNone(response.json()[0]["inventory_checked_on"])
        purchase = Purchase.objects.get(id=response.json()[0]["id"])
        self.assertIsNone(purchase.current_stock_quantity)
        self.assertIsNone(purchase.inventory_checked_on)

    # Regression guard: invoice_url is rendered as a link (staff UI, Django admin), so only a stored
    # /media/ path or an https URL is accepted; script-capable or other schemes are refused.
    def test_invoice_url_rejects_non_media_non_https_values(self):
        self.client.force_authenticate(self.user)
        rejected = [
            "javascript:void(0)",
            " JavaScript:void(0)",
            "data:text/plain,invoice",
            "http://example.com/inv.pdf",
            "//example.com/inv.pdf",
            "/media/../admin/",
            "/media/%2e%2e/api/purchases/",
            "/media/%2E%2E%2fapi/",
            "https://user:secret@files.example.com/inv.pdf",
            "https://user@files.example.com/inv.pdf",
            "/api/purchases/",
            "https:/no-host",
        ]
        purchase = Purchase.objects.create(
            order_date="2026-03-20",
            supplier=self.supplier,
            unit_of_measure=self.uom_pcs,
            part_name="Brake Disc",
            quantity=1,
            purchase_price="10.00",
        )
        for value in rejected:
            with self.subTest(value=value):
                create = self.client.post(
                    "/api/purchases/", self._purchase_payload(invoice_url=value), format="json"
                )
                self.assertEqual(create.status_code, 400)
                self.assertIn("invoice_url", create.json())

                update = self.client.patch(
                    f"/api/purchases/{purchase.id}", {"invoice_url": value}, format="json"
                )
                self.assertEqual(update.status_code, 400)
                self.assertIn("invoice_url", update.json())

                bulk = self.client.post(
                    "/api/purchases/bulk/",
                    {
                        "order_date": "2026-04-01",
                        "supplier_name": "Bulk Supplier",
                        "invoice_url": value,
                        "lines": [{"part_name": "Part A", "quantity": 1, "purchase_price": "10.00"}],
                    },
                    format="json",
                )
                self.assertEqual(bulk.status_code, 400)
                self.assertIn("invoice_url", bulk.json())
        purchase.refresh_from_db()
        self.assertEqual(purchase.invoice_url, "")
        self.assertFalse(Purchase.objects.exclude(invoice_url="").exists())

    def test_invoice_url_accepts_media_path_https_and_blank(self):
        self.client.force_authenticate(self.user)
        for value in ("/media/invoices/abc123.pdf", "https://files.example.com/inv.pdf", ""):
            with self.subTest(value=value):
                response = self.client.post(
                    "/api/purchases/", self._purchase_payload(invoice_url=value), format="json"
                )
                self.assertEqual(response.status_code, 201, response.content)
                self.assertEqual(response.json()["invoice_url"], value)

    # Regression guard: the data migration blanks invoice_url values stored before validation existed,
    # so no client (admin, staff UI) can open a disallowed scheme from a legacy row.
    def test_migration_blanks_disallowed_legacy_invoice_urls(self):
        import importlib

        from django.apps import apps as global_apps

        migration = importlib.import_module("purchases.migrations.0015_blank_disallowed_invoice_urls")
        values = {
            "javascript:void(0)": "",
            "http://example.com/inv.pdf": "",
            "/media/%2e%2e/api/": "",
            "https://user:secret@example.com/inv.pdf": "",
            "/media/invoices/ok.pdf": "/media/invoices/ok.pdf",
            "https://files.example.com/inv.pdf": "https://files.example.com/inv.pdf",
            "": "",
        }
        rows = {
            value: Purchase.objects.create(
                order_date="2026-03-20",
                supplier=self.supplier,
                unit_of_measure=self.uom_pcs,
                part_name="Legacy",
                quantity=1,
                purchase_price="1.00",
                invoice_url=value,
            )
            for value in values
        }

        migration.blank_disallowed_invoice_urls(global_apps, None)

        for value, expected in values.items():
            with self.subTest(value=value):
                rows[value].refresh_from_db()
                self.assertEqual(rows[value].invoice_url, expected)
        operation = migration.Migration.operations[0]
        self.assertTrue(operation.reversible)

    # Regression guard: rows stored before validation existed must not become clickable links in admin.
    def test_admin_invoice_link_only_links_allowed_urls(self):
        from django.contrib import admin as django_admin

        from .admin import PurchaseAdmin

        model_admin = PurchaseAdmin(Purchase, django_admin.site)
        purchase = Purchase(invoice_url="javascript:void(0)")
        rendered = str(model_admin.invoice_link(purchase))
        self.assertNotIn("<a", rendered)
        self.assertNotIn('href="javascript', rendered)

        purchase.invoice_url = "/media/invoices/abc.pdf"
        rendered = str(model_admin.invoice_link(purchase))
        self.assertIn('href="/media/invoices/abc.pdf"', rendered)

        purchase.invoice_url = ""
        self.assertEqual(model_admin.invoice_link(purchase), "—")

    def test_purchase_order_pdf_returns_pdf(self):
        self.client.force_authenticate(self.user)
        self.supplier.registered_address = "Supplier HQ, Warsaw"
        self.supplier.save(update_fields=["registered_address"])

        response = self.client.post(
            "/api/purchases/po/pdf/",
            {
                "order_date": "2026-03-20",
                "approximate_delivery_date": "2026-03-25",
                "supplier_name": "Existing Supplier",
                "is_shop_consumable": False,
                "lines": [
                    {
                        "part_name": "Brake Disc",
                        "quantity": "2",
                        "purchase_price": "89.99",
                        "unit_of_measure_id": self.uom_pcs.id,
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("po_existing_supplier_2026-03-20.pdf", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def _po_pdf(self, supplier_name, part_name):
        return self.client.post(
            "/api/purchases/po/pdf/",
            {
                "order_date": "2026-03-20",
                "supplier_name": supplier_name,
                "lines": [
                    {"part_name": part_name, "quantity": "1", "purchase_price": "10.00"},
                ],
            },
            format="json",
        )

    @staticmethod
    def _pdf_text(content):
        # Join wrapped table lines so a literal that spans a cell line break can still be matched.
        return " ".join(" ".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages).split())

    # Regression guard: names with markup characters used to make PO export fail with HTTP 500.
    def test_purchase_order_pdf_renders_markup_characters_literally(self):
        self.client.force_authenticate(self.user)
        self.supplier.name = "Smith & <Sons>"
        self.supplier.nip = "PL<1>"
        self.supplier.registered_address = "Main St <5> & Co"
        self.supplier.save()

        response = self._po_pdf("Smith & <Sons>", "Filter a<b <b>bold &amp; done")

        self.assertEqual(response.status_code, 200)
        text = self._pdf_text(response.content)
        for literal in ("Smith & <Sons>", "PL<1>", "Main St <5> & Co", "Filter a<b <b>bold &amp; done"):
            self.assertIn(literal, text)

    # Regression guard: an <img> tag in user text must stay text — no local file is read into the PDF.
    def test_purchase_order_pdf_does_not_embed_local_file_from_img_markup(self):
        self.client.force_authenticate(self.user)
        with tempfile.TemporaryDirectory() as tmp:
            image_path = os.path.join(tmp, "probe.png")
            Image.new("RGB", (4, 4), (255, 0, 0)).save(image_path)
            markup = f'<img src="{image_path}" width="4" height="4"/>'

            response = self._po_pdf("Existing Supplier", markup)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"/Subtype /Image", response.content)
        self.assertIn(markup, self._pdf_text(response.content))

    # Regression guard: an <img> URL in user text must not make the server issue an outbound request.
    def test_purchase_order_pdf_does_not_fetch_url_from_img_markup(self):
        self.client.force_authenticate(self.user)
        requests_seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 — stdlib hook name
                requests_seen.append(self.path)
                self.send_response(404)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            markup = f'<img src="http://127.0.0.1:{server.server_address[1]}/probe.png" width="4" height="4"/>'
            response = self._po_pdf("Existing Supplier", markup)
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(requests_seen, [])
        self.assertIn(markup, self._pdf_text(response.content))

    def test_purchase_order_pdf_requires_lines(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/api/purchases/po/pdf/",
            {
                "order_date": "2026-03-20",
                "supplier_name": "Existing Supplier",
                "lines": [],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_create_purchase_without_repair_or_vehicle(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/api/purchases/",
            self._purchase_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        purchase = Purchase.objects.get(id=response.json()["id"])
        self.assertEqual(purchase.repair_code, "")
        self.assertIsNone(purchase.vehicle)
        self.assertEqual(response.json()["repair_code"], "")
        self.assertIsNone(response.json()["vehicle"])
        self.assertFalse(response.json()["is_shop_consumable"])
        self.assertEqual(response.json()["unit_of_measure"]["code"], "pcs")

    def test_search_filters_by_part_name(self):
        self.client.force_authenticate(self.user)
        Purchase.objects.create(
            order_date="2026-03-20",
            part_name="Brake Pad",
            quantity=4,
            purchase_price="45.00",
            supplier=self.supplier,
            unit_of_measure=self.uom_pcs,
        )
        Purchase.objects.create(
            order_date="2026-03-21",
            part_name="Air Filter",
            quantity=1,
            purchase_price="12.00",
            supplier=self.supplier,
            unit_of_measure=self.uom_pcs,
        )

        response = self.client.get("/api/purchases/", {"q": "brake"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["part_name"], "Brake Pad")

    def test_detail_returns_nested_supplier_data(self):
        self.client.force_authenticate(self.user)
        purchase = Purchase.objects.create(
            order_date="2026-03-20",
            part_name="Spark Plug",
            quantity=4,
            purchase_price="8.50",
            supplier=self.supplier,
            unit_of_measure=self.uom_pcs,
        )

        response = self.client.get(f"/api/purchases/{purchase.id}")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["part_name"], "Spark Plug")
        self.assertIsInstance(data["supplier"], dict)
        self.assertEqual(data["supplier"]["name"], self.supplier.name)
        self.assertEqual(data["supplier"]["nip"], self.supplier.nip)

    def test_update_purchase_part_name(self):
        self.client.force_authenticate(self.user)
        purchase = Purchase.objects.create(
            order_date="2026-03-20",
            part_name="Old Part",
            quantity=1,
            purchase_price="20.00",
            supplier=self.supplier,
            unit_of_measure=self.uom_pcs,
        )

        response = self.client.patch(
            f"/api/purchases/{purchase.id}",
            {"part_name": "New Part"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["part_name"], "New Part")

    def test_update_purchase_delivered(self):
        self.client.force_authenticate(self.user)
        purchase = Purchase.objects.create(
            order_date="2026-03-20",
            part_name="Windshield",
            quantity=1,
            purchase_price="120.00",
            supplier=self.supplier,
            unit_of_measure=self.uom_pcs,
        )

        response = self.client.patch(
            f"/api/purchases/{purchase.id}",
            {"delivered": True},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["delivered"])
        purchase.refresh_from_db()
        self.assertTrue(purchase.delivered)

    def test_update_consumable_current_stock_quantity(self):
        self.client.force_authenticate(self.user)
        purchase = Purchase.objects.create(
            order_date="2026-03-20",
            part_name="Gloves",
            quantity=10,
            purchase_price="2.00",
            supplier=self.supplier,
            unit_of_measure=self.uom_pcs,
            is_shop_consumable=True,
        )

        response = self.client.patch(
            f"/api/purchases/{purchase.id}",
            {"current_stock_quantity": "4.50", "inventory_checked_on": "2026-03-25"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["current_stock_quantity"], "4.50")
        self.assertEqual(response.json()["inventory_checked_on"], "2026-03-25")
        purchase.refresh_from_db()
        self.assertEqual(str(purchase.current_stock_quantity), "4.50")
        self.assertEqual(str(purchase.inventory_checked_on), "2026-03-25")

    def test_update_consumable_can_clear_inventory_snapshot(self):
        self.client.force_authenticate(self.user)
        purchase = Purchase.objects.create(
            order_date="2026-03-20",
            part_name="Gloves",
            quantity=10,
            purchase_price="2.00",
            supplier=self.supplier,
            unit_of_measure=self.uom_pcs,
            is_shop_consumable=True,
            current_stock_quantity="4.50",
            inventory_checked_on="2026-03-25",
        )

        response = self.client.patch(
            f"/api/purchases/{purchase.id}",
            {"current_stock_quantity": None, "inventory_checked_on": None},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["current_stock_quantity"])
        self.assertIsNone(response.json()["inventory_checked_on"])
        purchase.refresh_from_db()
        self.assertIsNone(purchase.current_stock_quantity)
        self.assertIsNone(purchase.inventory_checked_on)

    def test_update_consumable_current_stock_quantity_requires_inventory_date_pair(self):
        self.client.force_authenticate(self.user)
        purchase = Purchase.objects.create(
            order_date="2026-03-20",
            part_name="Gloves",
            quantity=10,
            purchase_price="2.00",
            supplier=self.supplier,
            unit_of_measure=self.uom_pcs,
            is_shop_consumable=True,
        )

        response = self.client.patch(
            f"/api/purchases/{purchase.id}",
            {"current_stock_quantity": "4.50"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["current_stock_quantity"][0],
            "Inventory snapshot requires both date and quantity.",
        )

    def test_update_consumable_inventory_date_requires_quantity_pair(self):
        self.client.force_authenticate(self.user)
        purchase = Purchase.objects.create(
            order_date="2026-03-20",
            part_name="Gloves",
            quantity=10,
            purchase_price="2.00",
            supplier=self.supplier,
            unit_of_measure=self.uom_pcs,
            is_shop_consumable=True,
        )

        response = self.client.patch(
            f"/api/purchases/{purchase.id}",
            {"inventory_checked_on": "2026-03-25"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["inventory_checked_on"][0],
            "Inventory snapshot requires both date and quantity.",
        )

    def test_update_consumable_current_stock_quantity_rejects_value_above_quantity(self):
        self.client.force_authenticate(self.user)
        purchase = Purchase.objects.create(
            order_date="2026-03-20",
            part_name="Gloves",
            quantity=10,
            purchase_price="2.00",
            supplier=self.supplier,
            unit_of_measure=self.uom_pcs,
            is_shop_consumable=True,
        )

        response = self.client.patch(
            f"/api/purchases/{purchase.id}",
            {"current_stock_quantity": "10.01", "inventory_checked_on": "2026-03-25"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["current_stock_quantity"][0],
            "Inventory cannot exceed the purchased quantity.",
        )
        purchase.refresh_from_db()
        self.assertIsNone(purchase.current_stock_quantity)

    def test_delete_purchase(self):
        self.client.force_authenticate(self.user)
        purchase = Purchase.objects.create(
            order_date="2026-03-20",
            part_name="Disposable Part",
            quantity=1,
            purchase_price="5.00",
            supplier=self.supplier,
            unit_of_measure=self.uom_pcs,
        )

        response = self.client.delete(f"/api/purchases/{purchase.id}")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Purchase.objects.filter(id=purchase.id).exists())

    def test_filter_shop_consumable_param(self):
        self.client.force_authenticate(self.user)
        Purchase.objects.create(
            order_date="2026-03-20",
            part_name="Brake Disc",
            quantity=1,
            purchase_price="50.00",
            supplier=self.supplier,
            unit_of_measure=self.uom_pcs,
            is_shop_consumable=False,
        )
        Purchase.objects.create(
            order_date="2026-03-20",
            part_name="Gloves",
            quantity=10,
            purchase_price="2.00",
            supplier=self.supplier,
            unit_of_measure=self.uom_pcs,
            is_shop_consumable=True,
        )

        parts = self.client.get("/api/purchases/", {"shop_consumable": "false"})
        cons = self.client.get("/api/purchases/", {"shop_consumable": "true"})
        self.assertEqual(parts.status_code, 200)
        self.assertEqual(cons.status_code, 200)
        self.assertEqual(len(parts.json()["results"]), 1)
        self.assertEqual(len(cons.json()["results"]), 1)
        self.assertEqual(parts.json()["results"][0]["part_name"], "Brake Disc")
        self.assertEqual(cons.json()["results"][0]["part_name"], "Gloves")

    def test_list_units_of_measure(self):
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/purchases/units/")
        self.assertEqual(response.status_code, 200)
        codes = {row["code"] for row in response.json()}
        self.assertIn("pcs", codes)
        self.assertIn("L", codes)

    def test_staff_cannot_create_unit_of_measure(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/purchases/units/",
            {"code": "box", "name": "Box", "is_active": True, "sort_order": 99},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_and_list_inactive_units(self):
        admin = get_user_model().objects.create_user(
            email="admin-uom@test.local",
            password="admin12345",
            role="admin",
            is_staff=True,
        )
        UnitOfMeasure.objects.create(
            code="old-uom",
            name="Legacy",
            is_active=False,
            sort_order=999,
        )
        self.client.force_authenticate(self.user)
        staff_list = self.client.get("/api/purchases/units/")
        self.assertEqual(staff_list.status_code, 200)
        staff_codes = {row["code"] for row in staff_list.json()}
        self.assertNotIn("old-uom", staff_codes)

        self.client.force_authenticate(admin)
        admin_list = self.client.get("/api/purchases/units/", {"include_inactive": "true"})
        self.assertEqual(admin_list.status_code, 200)
        admin_codes = {row["code"] for row in admin_list.json()}
        self.assertIn("old-uom", admin_codes)

        response = self.client.post(
            "/api/purchases/units/",
            {"code": "srv", "name": "Service unit", "is_active": True, "sort_order": 15},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["code"], "srv")

    def test_staff_cannot_patch_unit_of_measure(self):
        self.client.force_authenticate(self.user)
        u = UnitOfMeasure.objects.get(code="L")
        response = self.client.patch(f"/api/purchases/units/{u.id}", {"name": "Litres"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_admin_cannot_delete_unit_referenced_by_purchase(self):
        admin = get_user_model().objects.create_user(
            email="admin-del@test.local",
            password="admin12345",
            role="admin",
            is_staff=True,
        )
        u = UnitOfMeasure.objects.create(code="del-uom", name="To delete", is_active=True, sort_order=900)
        Purchase.objects.create(
            order_date="2026-03-20",
            part_name="Part",
            quantity=1,
            purchase_price="10.00",
            supplier=self.supplier,
            unit_of_measure=u,
        )
        self.client.force_authenticate(admin)
        response = self.client.delete(f"/api/purchases/units/{u.id}")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(UnitOfMeasure.objects.filter(id=u.id).exists())

    def test_admin_can_reorder_units(self):
        admin = get_user_model().objects.create_user(
            email="admin-reorder@test.local",
            password="admin12345",
            role="admin",
            is_staff=True,
        )
        self.client.force_authenticate(admin)
        listed = self.client.get("/api/purchases/units/", {"include_inactive": "true"})
        self.assertEqual(listed.status_code, 200)
        ids = [row["id"] for row in listed.json()]
        rev = list(reversed(ids))
        resp = self.client.post("/api/purchases/units/reorder/", {"order": rev}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([row["id"] for row in resp.json()], rev)
        again = self.client.get("/api/purchases/units/", {"include_inactive": "true"})
        self.assertEqual([row["id"] for row in again.json()], rev)

    def test_staff_cannot_reorder_units(self):
        self.client.force_authenticate(self.user)
        listed = self.client.get("/api/purchases/units/")
        ids = [row["id"] for row in listed.json()]
        resp = self.client.post("/api/purchases/units/reorder/", {"order": list(reversed(ids))}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_reorder_units_requires_full_id_set(self):
        admin = get_user_model().objects.create_user(
            email="admin-reorder2@test.local",
            password="admin12345",
            role="admin",
            is_staff=True,
        )
        self.client.force_authenticate(admin)
        listed = self.client.get("/api/purchases/units/", {"include_inactive": "true"})
        ids = [row["id"] for row in listed.json()]
        resp = self.client.post("/api/purchases/units/reorder/", {"order": ids[:-1]}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_admin_create_unit_without_sort_order_appends(self):
        admin = get_user_model().objects.create_user(
            email="admin-append@test.local",
            password="admin12345",
            role="admin",
            is_staff=True,
        )
        self.client.force_authenticate(admin)
        resp = self.client.post(
            "/api/purchases/units/",
            {"code": "no-sort", "name": "No sort sent", "is_active": True},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIn("sort_order", resp.json())


class InvoiceParseApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.staff = get_user_model().objects.create_user(
            email="staff-invoice-parse@test.local",
            password="staff12345",
            role="staff",
        )
        self.admin = get_user_model().objects.create_user(
            email="admin-invoice-parse@test.local",
            password="admin12345",
            role="admin",
            is_staff=True,
        )

    def test_preview_parses_demo_pipe_line_with_template(self):
        template = InvoiceLineParseTemplate.objects.filter(name="Pipe table (demo PL)").first()
        self.assertIsNotNone(template)
        self.client.force_authenticate(self.staff)
        raw = (
            "  1  | Filtr oleju Bosch OF-512 (demo)                   |   2   | szt |    42,50   |      85,00    |  23%"
        )
        response = self.client.post(
            "/api/purchases/invoice-parse/preview/",
            {"raw_text": raw, "template_id": template.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["matched_count"], 1)
        self.assertEqual(body["lines"][0]["part_name"], "Filtr oleju Bosch OF-512 (demo)")
        self.assertEqual(body["lines"][0]["quantity"], 2)
        self.assertEqual(body["lines"][0]["purchase_price"], "85.00")
        self.assertEqual(body["lines"][0].get("uom_raw"), "szt")
        self.assertIn("supplier_resolution", body)
        self.assertEqual(body["supplier_resolution"].get("match"), "none")
        uom_res = body["lines"][0].get("uom_resolution") or {}
        self.assertEqual(uom_res.get("match"), "synonym")
        self.assertIsNotNone(body["lines"][0].get("unit_of_measure_id"))

    def test_preview_resolves_supplier_exact_and_warns_on_unknown_uom(self):
        template = InvoiceLineParseTemplate.objects.filter(name="Pipe table (demo PL)").first()
        self.assertIsNotNone(template)
        Supplier.objects.create(name="ACME Parts Demo", nip="")
        self.client.force_authenticate(self.staff)
        raw = (
            "Sprzedawca (Seller): ACME Parts Demo\n"
            "  1  | Filtr |   2   | xxxunk |    10,00   |      20,00    |  23%"
        )
        sup_pat = r"(?is)Sprzedawca\s*\([^)]*\)\s*:\s*(?P<supplier_name>[^\r\n]+)"
        response = self.client.post(
            "/api/purchases/invoice-parse/preview/",
            {"raw_text": raw, "template_id": template.pk, "supplier_pattern": sup_pat},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["supplier_resolution"]["match"], "exact")
        self.assertEqual(body["supplier_resolution"]["resolved_name"], "ACME Parts Demo")
        self.assertEqual(body["supplier_resolution"]["supplier_id"], Supplier.objects.get(name="ACME Parts Demo").id)
        self.assertEqual(body["lines"][0]["uom_resolution"]["match"], "none")
        self.assertTrue(any("not mapped" in w for w in body["warnings"]))

    def test_preview_resolves_supplier_via_alias(self):
        template = InvoiceLineParseTemplate.objects.filter(name="Pipe table (demo PL)").first()
        self.assertIsNotNone(template)
        canonical = Supplier.objects.create(name="Canonical Sp z o.o.", nip="")
        SupplierAlias.objects.create(supplier=canonical, alias_text="hurt acme sp. z o.o.")
        self.client.force_authenticate(self.staff)
        raw = (
            "Sprzedawca (Seller): hurt acme sp. z o.o.\n"
            "  1  | Filtr |   2   | szt |    10,00   |      20,00    |  23%"
        )
        sup_pat = r"(?is)Sprzedawca\s*\([^)]*\)\s*:\s*(?P<supplier_name>[^\r\n]+)"
        response = self.client.post(
            "/api/purchases/invoice-parse/preview/",
            {"raw_text": raw, "template_id": template.pk, "supplier_pattern": sup_pat},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["supplier_resolution"]["match"], "alias")
        self.assertEqual(body["supplier_resolution"]["resolved_name"], "Canonical Sp z o.o.")
        self.assertEqual(body["supplier_resolution"]["supplier_id"], canonical.id)

    # Regression guard: a staff-supplied pattern with catastrophic backtracking used to pin the worker.
    # It must now fail fast with a 400 instead of hanging or returning 500.
    SLOW_LINE_PATTERN = r"(?P<part_name>(?:a|aa)+)b(?P<quantity>\d)(?P<purchase_price>\d)"

    def test_preview_pathological_line_pattern_returns_400_within_time_bound(self):
        self.client.force_authenticate(self.staff)
        started = time.monotonic()

        response = self.client.post(
            "/api/purchases/invoice-parse/preview/",
            {"raw_text": "a" * 48, "line_pattern": self.SLOW_LINE_PATTERN},
            format="json",
        )

        elapsed = time.monotonic() - started
        self.assertEqual(response.status_code, 400)
        self.assertIn("too long to evaluate", response.json()["detail"])
        self.assertLess(elapsed, 5)

    def test_preview_pathological_supplier_pattern_returns_400_within_time_bound(self):
        template = InvoiceLineParseTemplate.objects.filter(name="Pipe table (demo PL)").first()
        self.assertIsNotNone(template)
        self.client.force_authenticate(self.staff)
        started = time.monotonic()

        response = self.client.post(
            "/api/purchases/invoice-parse/preview/",
            {
                "raw_text": "a" * 48,
                "template_id": template.pk,
                "supplier_pattern": r"(?P<supplier_name>(?:a|aa)+)b",
            },
            format="json",
        )

        elapsed = time.monotonic() - started
        self.assertEqual(response.status_code, 400)
        self.assertIn("too long to evaluate", response.json()["detail"])
        self.assertLess(elapsed, 5)

    def test_preview_rejects_overlong_pattern_and_text(self):
        from .invoice_parse.constants import MAX_INVOICE_TEXT_CHARS, MAX_REGEX_PATTERN_CHARS

        self.client.force_authenticate(self.staff)
        long_pattern = r"(?P<part_name>\w+) (?P<quantity>\d+) (?P<purchase_price>\d+)" + "x?" * MAX_REGEX_PATTERN_CHARS
        response = self.client.post(
            "/api/purchases/invoice-parse/preview/",
            {"raw_text": "Filter 1 10", "line_pattern": long_pattern},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("line_pattern", response.json())

        response = self.client.post(
            "/api/purchases/invoice-parse/preview/",
            {
                "raw_text": "Filter 1 10\n" * (MAX_INVOICE_TEXT_CHARS // 10),
                "line_pattern": r"(?P<part_name>\w+) (?P<quantity>\d+) (?P<purchase_price>\d+)",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("raw_text", response.json())

    def test_suggest_rejects_overlong_text(self):
        from .invoice_parse.constants import MAX_INVOICE_TEXT_CHARS

        self.client.force_authenticate(self.staff)
        response = self.client.post(
            "/api/purchases/invoice-parse/suggest/",
            {"raw_text": "x" * (MAX_INVOICE_TEXT_CHARS + 1)},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    # Regression guard: extracted file text is capped too, not only pasted text.
    def test_preview_rejects_overlong_text_extracted_from_file(self):
        from .invoice_parse.constants import MAX_INVOICE_TEXT_CHARS

        self.client.force_authenticate(self.staff)
        upload = SimpleUploadedFile("invoice.txt", b"y" * (MAX_INVOICE_TEXT_CHARS + 1), content_type="text/plain")
        response = self.client.post(
            "/api/purchases/invoice-parse/preview/",
            {"file": upload, "line_pattern": r"(?P<part_name>\w+) (?P<quantity>\d+) (?P<purchase_price>\d+)"},
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("too long", response.json()["detail"])

    # Regression guard: OCR/extract endpoints enforce the same per-file cap as the invoice upload.
    def test_parse_endpoints_reject_oversized_file(self):
        from .invoice_parse.constants import MAX_INVOICE_PARSE_FILE_BYTES

        self.client.force_authenticate(self.staff)
        for url, extra in (
            ("/api/purchases/invoice-parse/extract/", {}),
            ("/api/purchases/invoice-parse/suggest/", {}),
            ("/api/purchases/invoice-parse/preview/", {"line_pattern": r"(?P<part_name>\w+) (?P<quantity>\d+) (?P<purchase_price>\d+)"}),
        ):
            with self.subTest(url=url):
                upload = SimpleUploadedFile(
                    "invoice.txt", b"z" * (MAX_INVOICE_PARSE_FILE_BYTES + 1), content_type="text/plain"
                )
                response = self.client.post(url, {"file": upload, **extra}, format="multipart")
                self.assertEqual(response.status_code, 400)
                self.assertIn("file", response.json())

    def test_template_rejects_overlong_pattern(self):
        from .invoice_parse.constants import MAX_REGEX_PATTERN_CHARS

        self.client.force_authenticate(self.admin)
        response = self.client.post(
            "/api/purchases/invoice-parse-templates/",
            {
                "name": "Too long",
                "line_pattern": r"(?P<part_name>\w+) (?P<quantity>\d+) (?P<purchase_price>\d+)" + "x?" * MAX_REGEX_PATTERN_CHARS,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("line_pattern", response.json())

    def test_suggest_returns_pattern_for_multi_line_demo(self):
        self.client.force_authenticate(self.staff)
        raw = (
            "  1  | Part A |   1   | szt | 10,00 | 10,00\n"
            "  2  | Part B |   2   | szt | 5,00 | 10,00\n"
        )
        response = self.client.post("/api/purchases/invoice-parse/suggest/", {"raw_text": raw}, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("matched"))
        self.assertIn("line_pattern", data)
        self.assertIn("supplier_resolution", data)
        pl0 = data["preview_lines"][0]
        self.assertEqual(pl0.get("uom_raw"), "szt")
        self.assertIsNotNone(pl0.get("unit_of_measure_id"))

    def test_suggest_extracts_supplier_plain_sprzedawca_polish(self):
        """Polish invoices often use 'Sprzedawca:' without parentheses (see docs/samples/sample-invoice-pl-01)."""
        self.client.force_authenticate(self.staff)
        raw = (
            "Sprzedawca: AUTO-CZĘŚCI WZÓR SP. Z O.O.\n"
            "            ul. Magazynowa 7\n"
            "  1  | Part A |   1   | szt | 10,00 | 10,00\n"
            "  2  | Part B |   2   | szt | 5,00 | 10,00\n"
        )
        response = self.client.post("/api/purchases/invoice-parse/suggest/", {"raw_text": raw}, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("matched"))
        preview_name = (data.get("preview_supplier_name") or "").strip()
        self.assertIn("AUTO-CZĘŚCI", preview_name)
        raw_res = (data.get("supplier_resolution") or {}).get("raw_name") or ""
        self.assertIn("AUTO-CZĘŚCI", raw_res)

    def test_suggest_accepts_plain_text_file_multipart(self):
        self.client.force_authenticate(self.staff)
        raw = (
            "  1  | Part A |   1   | szt | 10,00 | 10,00\n"
            "  2  | Part B |   2   | szt | 5,00 | 10,00\n"
        )
        upload = SimpleUploadedFile("demo.txt", raw.encode("utf-8"), content_type="text/plain")
        response = self.client.post("/api/purchases/invoice-parse/suggest/", {"file": upload}, format="multipart")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("matched"))
        self.assertIn("line_pattern", data)

    def test_suggest_multipart_pdf_text_layer_matches_plaintext_demo(self):
        """Generated PDF uses a text layer — same suggest outcome as raw_text for the PL table demo."""
        from purchases.invoice_parse.demo_invoice_pdf import DEMO_PL_TABLE_INVOICE_TEXT, build_sample_pl_table_invoice_pdf_bytes

        self.client.force_authenticate(self.staff)
        raw = DEMO_PL_TABLE_INVOICE_TEXT.strip()
        r_txt = self.client.post("/api/purchases/invoice-parse/suggest/", {"raw_text": raw}, format="json")
        self.assertEqual(r_txt.status_code, 200)
        d_txt = r_txt.json()
        self.assertTrue(d_txt.get("matched"))

        pdf_bytes = build_sample_pl_table_invoice_pdf_bytes()
        self.assertGreaterEqual(len(pdf_bytes), 500)
        upload = SimpleUploadedFile("sample-invoice-pl-01-demo.pdf", pdf_bytes, content_type="application/pdf")
        r_pdf = self.client.post("/api/purchases/invoice-parse/suggest/", {"file": upload}, format="multipart")
        self.assertEqual(r_pdf.status_code, 200)
        d_pdf = r_pdf.json()
        self.assertTrue(d_pdf.get("matched"))
        self.assertIn("AUTO-CZĘŚCI", (d_pdf.get("preview_supplier_name") or ""))
        self.assertEqual(len(d_pdf.get("preview_lines") or []), len(d_txt.get("preview_lines") or []))
        for i, (a, b) in enumerate(zip(d_pdf["preview_lines"], d_txt["preview_lines"], strict=True)):
            self.assertEqual(a.get("part_name"), b.get("part_name"), msg=f"line {i} part_name")
            self.assertEqual(a.get("quantity"), b.get("quantity"), msg=f"line {i} quantity")
            self.assertEqual(a.get("uom_raw"), b.get("uom_raw"), msg=f"line {i} uom")

    def test_extract_multipart_pdf_demo_contains_sprzedawca(self):
        from purchases.invoice_parse.demo_invoice_pdf import build_sample_pl_table_invoice_pdf_bytes

        self.client.force_authenticate(self.staff)
        pdf_bytes = build_sample_pl_table_invoice_pdf_bytes()
        upload = SimpleUploadedFile("demo.pdf", pdf_bytes, content_type="application/pdf")
        response = self.client.post("/api/purchases/invoice-parse/extract/", {"file": upload}, format="multipart")
        self.assertEqual(response.status_code, 200)
        text = (response.json().get("raw_text") or "").lower()
        self.assertIn("sprzedawca", text)
        self.assertIn("auto-części", text)

    def test_extract_returns_text_from_plain_file(self):
        self.client.force_authenticate(self.staff)
        raw = "Sprzedawca: ACME\nLine one\n"
        upload = SimpleUploadedFile("x.txt", raw.encode("utf-8"), content_type="text/plain")
        response = self.client.post("/api/purchases/invoice-parse/extract/", {"file": upload}, format="multipart")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("raw_text"), raw.strip())

    def test_staff_cannot_create_template(self):
        self.client.force_authenticate(self.staff)
        response = self.client.post(
            "/api/purchases/invoice-parse-templates/",
            {
                "name": "X",
                "description": "",
                "line_pattern": r"(?P<part_name>.+)\s(?P<quantity>\d+)\s(?P<purchase_price>[\d.]+)",
                "is_active": True,
                "sort_order": 99,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_create_template_requires_named_groups(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            "/api/purchases/invoice-parse-templates/",
            {
                "name": "Bad",
                "description": "",
                "line_pattern": r"(?P<x>.*)",
                "is_active": True,
                "sort_order": 5,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("line_pattern", response.json())

    def test_staff_lists_active_templates(self):
        self.client.force_authenticate(self.staff)
        response = self.client.get("/api/purchases/invoice-parse-templates/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreaterEqual(len(data), 1)


@unittest.skipUnless(shutil.which("tesseract"), "tesseract not installed")
class InvoiceOcrExtractTests(TestCase):
    """Requires Tesseract + language packs on PATH (Docker image and CI install them)."""

    def test_extract_text_from_minimal_png_does_not_crash(self):
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        upload = SimpleUploadedFile("tiny.png", png, content_type="image/png")
        text = extract_text_from_file(upload)
        self.assertIsInstance(text, str)
