import { describe, expect, it } from "vitest";
import { isAllowedInvoiceUrl } from "./invoiceUrl";

// Regression guard: the staff UI opens invoice_url in a new window, so values outside the backend
// allowlist (e.g. a script-capable scheme stored before validation existed) must never be opened.
describe("isAllowedInvoiceUrl", () => {
  it.each(["/media/invoices/abc.pdf", "/media/invoices/a%20b.pdf", "https://files.example.com/inv.pdf"])(
    "allows %s",
    (url) => {
      expect(isAllowedInvoiceUrl(url)).toBe(true);
    }
  );

  it.each([
    "",
    "javascript:void(0)",
    "JavaScript:void(0)",
    "data:text/plain,invoice",
    "http://example.com/inv.pdf",
    "//example.com/inv.pdf",
    "/api/purchases/",
    "/media/../admin/",
    "/media/%2e%2e/api/",
    "/media/%2E%2E%2fapi/",
    "/media/%zz",
    "https://user:secret@example.com/inv.pdf",
    "https://user@example.com/inv.pdf",
    " https://example.com/inv.pdf",
    "/media\\..\\admin",
  ])("rejects %s", (url) => {
    expect(isAllowedInvoiceUrl(url)).toBe(false);
  });
});
