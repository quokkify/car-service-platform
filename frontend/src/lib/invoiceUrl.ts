const MEDIA_PREFIX = "/media/";

/**
 * Mirrors the backend rule (purchases.models.is_allowed_invoice_url): blank is not openable;
 * otherwise only an uploaded `/media/…` path or an absolute https URL without credentials.
 */
export function isAllowedInvoiceUrl(url: string): boolean {
  if (!url) return false;
  if (/[\s\u0000-\u001f\\]/.test(url)) return false;

  if (url.startsWith(MEDIA_PREFIX)) {
    const path = url.split(/[?#]/, 1)[0];
    let decoded: string;
    try {
      decoded = decodeURIComponent(path);
    } catch {
      return false;
    }
    return !decoded.includes("\\") && !decoded.split("/").includes("..");
  }

  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  return parsed.protocol === "https:" && parsed.hostname !== "" && !parsed.username && !parsed.password;
}
