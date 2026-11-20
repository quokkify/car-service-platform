from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.db import migrations


def _is_allowed(url):
    # Frozen copy of purchases.models.is_allowed_invoice_url at the time of this migration.
    if not url:
        return True
    if any(ch.isspace() or ord(ch) < 32 or ch == "\\" for ch in url):
        return False
    parts = urlsplit(url)
    if parts.scheme == "https":
        return bool(parts.hostname) and "@" not in parts.netloc
    if parts.scheme or parts.netloc:
        return False
    path = unquote(parts.path)
    return path.startswith(settings.MEDIA_URL) and ".." not in path.split("/") and "\\" not in path


def blank_disallowed_invoice_urls(apps, schema_editor):
    Purchase = apps.get_model("purchases", "Purchase")
    bad_ids = [
        pk
        for pk, url in Purchase.objects.exclude(invoice_url="").values_list("pk", "invoice_url").iterator()
        if not _is_allowed(url)
    ]
    if bad_ids:
        Purchase.objects.filter(pk__in=bad_ids).update(invoice_url="")


class Migration(migrations.Migration):
    dependencies = [
        ("purchases", "0014_merge_purchase_decimal_and_invoice_templates"),
    ]

    operations = [
        migrations.RunPython(blank_disallowed_invoice_urls, migrations.RunPython.noop),
    ]
