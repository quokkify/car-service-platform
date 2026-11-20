"""Invoice plain-text extraction (OCR) and regex-based line parsing."""

from .catalog_resolvers import enrich_parsed_lines, resolve_supplier_name, resolve_uom_token
from .constants import (
    MAX_INVOICE_PARSE_FILE_BYTES,
    MAX_INVOICE_TEXT_CHARS,
    MAX_REGEX_PATTERN_CHARS,
    REQUIRED_REGEX_GROUPS,
    SUPPLIER_REGEX_GROUP,
)
from .decimal_norm import normalize_decimal
from .regex_engine import (
    SUGGESTION_CANDIDATES,
    SUPPLIER_PATTERN_CANDIDATES,
    RegexLimitError,
    compile_line_pattern,
    compile_pattern_or_raise,
    extract_supplier,
    new_regex_deadline,
    parse_invoice_lines,
    suggest_line_pattern,
    suggest_supplier_pattern,
)
from .text_extract import extract_text_from_file

__all__ = [
    "MAX_INVOICE_PARSE_FILE_BYTES",
    "MAX_INVOICE_TEXT_CHARS",
    "MAX_REGEX_PATTERN_CHARS",
    "RegexLimitError",
    "enrich_parsed_lines",
    "resolve_supplier_name",
    "resolve_uom_token",
    "REQUIRED_REGEX_GROUPS",
    "SUPPLIER_REGEX_GROUP",
    "SUGGESTION_CANDIDATES",
    "SUPPLIER_PATTERN_CANDIDATES",
    "compile_line_pattern",
    "compile_pattern_or_raise",
    "extract_supplier",
    "new_regex_deadline",
    "extract_text_from_file",
    "normalize_decimal",
    "parse_invoice_lines",
    "suggest_line_pattern",
    "suggest_supplier_pattern",
]
