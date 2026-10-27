import phonenumbers
from phonenumbers import geocoder

REGION = "PL"
TYPE_NAMES = {
    value: name.lower() for name, value in vars(phonenumbers.PhoneNumberType).items() if isinstance(value, int)
}


class InvalidNumber(ValueError):
    pass


def normalize(raw: str) -> int:
    """Parse a phone number into E.164 digits without '+', e.g. 48717777777.

    That integer form is what iOS CallKit's Call Directory extension expects.
    """
    try:
        parsed = phonenumbers.parse(raw, REGION)
    except phonenumbers.NumberParseException as exc:
        raise InvalidNumber(f"Cannot parse phone number {raw!r}: {exc}") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise InvalidNumber(f"Invalid phone number {raw!r}")
    return to_int(parsed)


def to_int(parsed: phonenumbers.PhoneNumber) -> int:
    return int(phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)[1:])


def normalize_prefix(raw: str) -> str:
    """'+44 70' or '0044 70' -> '4470': the start of international numbers, country code included."""
    text = "".join(raw.split()).replace("-", "")
    digits = text[1:] if text.startswith("+") else text[2:] if text.startswith("00") else ""
    if not (digits.isdigit() and len(digits) <= 15 and _country_code(digits)):
        raise InvalidNumber(f"Write the prefix with its country code, e.g. +44 70, not {raw!r}")
    return digits


def format_prefix(prefix: str) -> str:
    """'44207946' -> '+44 20 7946', grouped like the start of a full number."""
    formatter = phonenumbers.AsYouTypeFormatter("ZZ")
    for char in f"+{prefix}":
        text = formatter.input_digit(char)
    return text.strip()


def _country_code(digits: str) -> str | None:
    # Country codes are prefix-free, so at most one of these matches.
    return next((digits[:i] for i in (1, 2, 3)
                 if len(digits) >= i and int(digits[:i]) in phonenumbers.COUNTRY_CODE_TO_REGION_CODE), None)


def format_international(number: int) -> str:
    parsed = phonenumbers.parse(f"+{number}")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)


def describe(number: int) -> tuple[str, str | None]:
    """Number type ("mobile", "fixed_line", "voip", "premium_rate", ...) and where it is from:
    the city for Polish landlines, otherwise the country."""
    parsed = phonenumbers.parse(f"+{number}")
    kind = TYPE_NAMES.get(phonenumbers.number_type(parsed), "unknown")
    return kind, geocoder.description_for_number(parsed, "pl") or None
