import re


LETTER_PATTERN = re.compile(r'[A-Za-z]')
INVALID_SYMBOL_PATTERN = re.compile(r'[^0-9+\s]')


def format_indian_phone_display(phone_digits):
    digits = ''.join(ch for ch in (phone_digits or '') if ch.isdigit())[:10]
    if len(digits) <= 5:
        return digits
    return f"{digits[:5]} {digits[5:]}"


def phone_lookup_variants(phone_digits):
    digits = ''.join(ch for ch in (phone_digits or '') if ch.isdigit())[:10]
    if not digits:
        return []

    formatted = format_indian_phone_display(digits)
    variants = [
        digits,
        formatted,
        f'+91{digits}',
        f'+91 {digits}',
        f'+91 {formatted}',
        f'91{digits}',
        f'91 {digits}',
        f'91 {formatted}',
    ]
    unique_variants = []
    seen = set()
    for value in variants:
        if value and value not in seen:
            unique_variants.append(value)
            seen.add(value)
    return unique_variants


def normalize_indian_phone(raw_value, *, required=True, field_label='Phone number'):
    raw_phone = (raw_value or '').strip()
    if not raw_phone:
        if required:
            return '', f'{field_label} is required.'
        return '', None

    if LETTER_PATTERN.search(raw_phone):
        return '', f'{field_label} can contain numbers only. Alphabets are not allowed.'

    if INVALID_SYMBOL_PATTERN.search(raw_phone):
        return '', f'{field_label} can contain numbers only. Symbols are not allowed.'

    if raw_phone.startswith('+') and not raw_phone.startswith('+91'):
        return '', f'{field_label} must be an Indian number. Use +91 or enter 10 digits.'

    digits = ''.join(ch for ch in raw_phone if ch.isdigit())
    if len(digits) > 10 and digits.startswith('91'):
        digits = digits[2:]

    if len(digits) != 10:
        return '', f'{field_label} must be exactly 10 digits.'

    return digits, None
