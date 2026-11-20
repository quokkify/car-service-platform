import os
import platform
import time

import django
from django.conf import settings
from django.db import connection
from django.utils.http import content_disposition_header
from django.views.static import serve
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

_start_time = time.time()

# Inert types the staff UI opens in a tab (invoice scans, completion PDFs); everything else downloads.
INLINE_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/webp"})


class HealthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        db_ok = True
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception:
            db_ok = False

        status_code = 200 if db_ok else 503
        return Response(
            {
                "status": "ok" if db_ok else "degraded",
                "db": db_ok,
                "service": "car-service-platform",
            },
            status=status_code,
        )


class VersionView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        uptime_seconds = int(time.time() - _start_time)
        return Response(
            {
                "service": "car-service-platform",
                "commit": os.environ.get("GIT_COMMIT", "unknown"),
                "python": platform.python_version(),
                "django": django.__version__,
                "uptime_seconds": uptime_seconds,
                "debug": os.environ.get("DJANGO_DEBUG", "False").lower() in ("true", "1"),
            }
        )


class ProtectedMediaView(APIView):
    """Serve a file from MEDIA_ROOT to logged-in users only; uploaded active content never renders inline."""

    permission_classes = [IsAuthenticated]

    def get(self, request, path):
        response = serve(request, path, document_root=settings.MEDIA_ROOT)
        response["X-Content-Type-Options"] = "nosniff"
        if response.status_code == 200:
            content_type = response["Content-Type"].split(";")[0].strip().lower()
            as_attachment = content_type not in INLINE_MEDIA_TYPES
            response["Content-Disposition"] = content_disposition_header(as_attachment, os.path.basename(path))
        return response
