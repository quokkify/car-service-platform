"""Regex-based line parsing and supplier extraction for invoice plain text."""

from __future__ import annotations

import decimal
import logging
import time
from typing import Any

# ``regex`` instead of ``re``: same syntax, but matching accepts a timeout, so a pattern with
# catastrophic backtracking cannot stall the worker.
import regex

from .constants import (
    MAX_REGEX_PATTERN_CHARS,
    REGEX_TIME_BUDGET_SECONDS,
    REQUIRED_REGEX_GROUPS,
    SUPPLIER_REGEX_GROUP,
)
from .decimal_norm import normalize_decimal

logger = logging.getLogger(__name__)


class RegexLimitError(ValueError):
    """Pattern rejected by a size or time limit; the message is safe to show to the client."""


def new_regex_deadline() -> float:
    return time.monotonic() + REGEX_TIME_BUDGET_SECONDS


def _search(rx: regex.Pattern, text: str, deadline: float):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RegexLimitError("Pattern took too long to evaluate; simplify the pattern.")
    try:
        return rx.search(text, timeout=remaining)
    except TimeoutError as exc:
        raise RegexLimitError("Pattern took too long to evaluate; simplify the pattern.") from exc


def compile_pattern_or_raise(pattern: str) -> regex.Pattern:
    if len(pattern) > MAX_REGEX_PATTERN_CHARS:
        raise RegexLimitError(f"Pattern is too long (max {MAX_REGEX_PATTERN_CHARS} characters).")
    try:
        return regex.compile(pattern)
    except regex.error as exc:
        raise ValueError(f"Invalid regex: {exc}") from exc


def compile_line_pattern(pattern: str) -> regex.Pattern:
    return compile_pattern_or_raise(pattern)


def parse_invoice_lines(
    raw_text: str, pattern: str, deadline: float | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Scan each non-empty line; if the regex finds a match with required named groups, emit one row.

    Each emitted row: part_name (str), quantity (int), purchase_price (str decimal).
    Raises ``RegexLimitError`` when matching exceeds the time budget (``deadline``, monotonic seconds).
    """
    if deadline is None:
        deadline = new_regex_deadline()
    rx = compile_line_pattern(pattern)
    try:
        groupindex = rx.groupindex
    except AttributeError:
        groupindex = {}
    missing = REQUIRED_REGEX_GROUPS - frozenset(groupindex.keys())
    if missing:
        raise ValueError(f"Regex must define named groups: {', '.join(sorted(REQUIRED_REGEX_GROUPS))}")

    lines_out: list[dict[str, Any]] = []
    warnings: list[str] = []

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if set(line) <= {"-", "=", "|", "."}:
            continue
        m = _search(rx, line, deadline)
        if not m:
            continue
        gd = m.groupdict()
        try:
            part = (gd.get("part_name") or "").strip()
            if not part:
                continue
            qty_raw = (gd.get("quantity") or "").strip()
            price_raw = (gd.get("purchase_price") or "").strip()
            if not qty_raw or not price_raw:
                continue
            qty = int(qty_raw)
            if qty < 1:
                warnings.append(f"Skipped non-positive quantity on line: {line[:120]}")
                continue
            price = normalize_decimal(price_raw)
            if price < 0:
                warnings.append(f"Skipped negative price on line: {line[:120]}")
                continue
        except (ValueError, TypeError, decimal.InvalidOperation) as exc:
            logger.debug("Invoice line parse skipped: %s | line: %s", exc, line[:120])
            warnings.append(f"Skipped line (could not parse values): {line[:120]}")
            continue

        row: dict[str, Any] = {
            "part_name": part[:255],
            "quantity": qty,
            "purchase_price": str(price),
        }
        uom_raw: str | None = None
        for key in ("uom", "unit_label", "unit_code", "jm"):
            v = gd.get(key)
            if v is not None and str(v).strip():
                uom_raw = str(v).strip()[:64]
                break
        if uom_raw:
            row["uom_raw"] = uom_raw

        lines_out.append(row)

    return lines_out, warnings


def extract_supplier(
    raw_text: str, supplier_pattern: str | None, deadline: float | None = None
) -> tuple[str | None, list[str]]:
    """
    Run one regex over the full OCR/text document; must define named group supplier_name.

    Raises ``RegexLimitError`` when the pattern is too long or matching exceeds the time budget.
    """
    warnings: list[str] = []
    pat = (supplier_pattern or "").strip()
    if not pat:
        return None, warnings
    if deadline is None:
        deadline = new_regex_deadline()
    try:
        rx = compile_pattern_or_raise(pat)
    except RegexLimitError:
        raise
    except ValueError as exc:
        logger.debug("Supplier regex invalid: %s", exc)
        warnings.append("Supplier regex pattern is invalid.")
        return None, warnings
    if SUPPLIER_REGEX_GROUP not in rx.groupindex:
        warnings.append(f"Supplier regex must define named group (?P<{SUPPLIER_REGEX_GROUP}>…).")
        return None, warnings
    m = _search(rx, raw_text, deadline)
    if not m:
        warnings.append("Supplier regex did not match the document text.")
        return None, warnings
    name = (m.groupdict().get(SUPPLIER_REGEX_GROUP) or "").strip()
    if not name:
        return None, warnings
    return name[:255], warnings


# Heuristic supplier-line patterns (Polish / generic); first match wins.
SUPPLIER_PATTERN_CANDIDATES: list[tuple[str, str]] = [
    (
        "PL Sprzedawca (Seller): …",
        r"(?is)Sprzedawca\s*\([^)]*\)\s*:\s*(?P<supplier_name>[^\r\n]+)",
    ),
    (
        "PL Sprzedawca: … (no parentheses; common PL invoices)",
        r"(?is)Sprzedawca\s*:\s*(?P<supplier_name>[^\r\n]+)",
    ),
    (
        "EN Vendor: …",
        r"(?is)Vendor\s*:\s*(?P<supplier_name>[^\r\n]+)",
    ),
    (
        "PL Dostawca: …",
        r"(?is)Dostawca\s*:\s*(?P<supplier_name>[^\r\n]+)",
    ),
]


def suggest_supplier_pattern(raw_text: str) -> tuple[str | None, str | None]:
    """Return (pattern, preview_supplier_name) or (None, None)."""
    deadline = new_regex_deadline()
    for _label, pattern in SUPPLIER_PATTERN_CANDIDATES:
        name, _w = extract_supplier(raw_text, pattern, deadline)
        if name:
            return pattern, name
    return None, None


# Built-in patterns tried by /invoice-parse/suggest/ (name, pattern, min_matches)
SUGGESTION_CANDIDATES: list[tuple[str, str, int]] = [
    (
        "Pipe table (demo PL)",
        r"^\s*\d+\s*\|\s*(?P<part_name>.+?)\s*\|\s*(?P<quantity>\d+)\s*\|\s*(?P<uom>\S+)\s*\|\s*[\d\s.,]+\s*\|\s*(?P<purchase_price>[\d\s.,]+)",
        2,
    ),
    (
        "Tab-separated line total",
        r"(?P<part_name>[^\t]+)\t+(?P<quantity>\d+)\t+(?P<purchase_price>[\d\s.,]+)\s*$",
        2,
    ),
    (
        "Trailing qty and price (flex)",
        r"(?P<part_name>.+?)\s+(?P<quantity>\d+)\s+(?P<purchase_price>[\d\s.,]+)\s*$",
        3,
    ),
]


def suggest_line_pattern(raw_text: str) -> tuple[str | None, str | None, list[dict[str, Any]]]:
    """
    Pick the candidate pattern with the most parsed lines (respecting min_matches).

    Returns (pattern, candidate_name, preview_lines) or (None, None, []).
    """
    best: tuple[int, str, str, list[dict[str, Any]]] | None = None
    deadline = new_regex_deadline()
    for label, pattern, minimum in SUGGESTION_CANDIDATES:
        try:
            rows, _warnings = parse_invoice_lines(raw_text, pattern, deadline)
        except RegexLimitError:
            raise
        except ValueError:
            continue
        if len(rows) < minimum:
            continue
        score = len(rows)
        if best is None or score > best[0]:
            best = (score, label, pattern, rows[:20])

    if best is None:
        return None, None, []
    _score, label, pattern, preview = best
    return pattern, label, preview
