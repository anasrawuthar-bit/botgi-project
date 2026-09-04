import re
from decimal import Decimal

from django.core.exceptions import ValidationError


GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
STATE_CODE_RE = re.compile(r"^[0-9]{2}$")
HSN_SAC_RE = re.compile(r"^[0-9]{4}([0-9]{2}){0,2}$")


def normalize_compact_code(value):
    return re.sub(r"\s+", "", (value or "")).strip().upper()


def normalize_text_code(value):
    return (value or "").strip().upper()


def validate_gstin(value):
    normalized = normalize_compact_code(value)
    if normalized and not GSTIN_RE.fullmatch(normalized):
        raise ValidationError("Enter a valid 15-character GSTIN.")


def validate_pan(value):
    normalized = normalize_compact_code(value)
    if normalized and not PAN_RE.fullmatch(normalized):
        raise ValidationError("Enter a valid PAN in the format AAAAA0000A.")


def validate_state_code(value):
    normalized = normalize_compact_code(value)
    if normalized and not STATE_CODE_RE.fullmatch(normalized):
        raise ValidationError("Enter a valid 2-digit GST state code.")


def validate_hsn_sac_code(value):
    normalized = normalize_compact_code(value)
    if normalized and not HSN_SAC_RE.fullmatch(normalized):
        raise ValidationError("HSN/SAC must be 4, 6, or 8 digits.")


def effective_tax_rate(gst_rate, tax_category):
    if tax_category != "taxable":
        return Decimal("0.00")
    return (gst_rate or Decimal("0.00")).quantize(Decimal("0.01"))
