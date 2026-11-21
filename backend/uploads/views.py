import os
import uuid

from django.core.files.storage import default_storage
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

# Keep in sync with invoice text/OCR pipeline (see purchases invoice-parse) — plain .txt imports must link too.
# Only passive document types: anything a browser can execute (HTML, SVG, XML) must never land under /media/.
OLE2_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_SIGNATURE = b"PK\x03\x04"
JPEG_SIGNATURE = b"\xff\xd8\xff"
TIFF_SIGNATURES = (b"II*\x00", b"MM\x00*")
TEXT_EXTENSIONS = {".txt", ".text"}
BINARY_SIGNATURES = {
    ".pdf": (b"%PDF-",),
    ".jpg": (JPEG_SIGNATURE,),
    ".jpeg": (JPEG_SIGNATURE,),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".tif": TIFF_SIGNATURES,
    ".tiff": TIFF_SIGNATURES,
    ".doc": (OLE2_SIGNATURE,),
    ".xls": (OLE2_SIGNATURE,),
    ".docx": (ZIP_SIGNATURE,),
    ".xlsx": (ZIP_SIGNATURE,),
}
ALLOWED_EXTENSIONS = TEXT_EXTENSIONS | set(BINARY_SIGNATURES) | {".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024
SNIFF_BYTES = 1024
UTF8_BOM = b"\xef\xbb\xbf"


def _content_matches_extension(ext: str, head: bytes) -> bool:
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ext in TEXT_EXTENSIONS:
        # Text is served as text/plain; refuse markup so no browser can sniff it as HTML/SVG.
        return not head.removeprefix(UTF8_BOM).lstrip().startswith(b"<")
    return head.startswith(BINARY_SIGNATURES[ext])


class InvoiceUploadView(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request):
        file = request.FILES.get("file")
        if not file:
            return Response({"detail": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        ext = os.path.splitext(file.name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return Response({"detail": "File type not allowed."}, status=status.HTTP_400_BAD_REQUEST)

        if file.size > MAX_FILE_SIZE:
            return Response({"detail": "File too large (max 10 MB)."}, status=status.HTTP_400_BAD_REQUEST)

        file.seek(0)
        head = file.read(SNIFF_BYTES)
        file.seek(0)
        if not _content_matches_extension(ext, head):
            return Response(
                {"detail": "File content does not match its type."}, status=status.HTTP_400_BAD_REQUEST
            )

        filename = f"{uuid.uuid4().hex}{ext}"
        storage_path = default_storage.save(f"invoices/{filename}", file)
        url = default_storage.url(storage_path)
        return Response({"url": url, "name": file.name}, status=status.HTTP_201_CREATED)
