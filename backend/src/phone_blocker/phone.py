import phonenumbers

REGION = "PL"


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


def format_international(number: int) -> str:
    parsed = phonenumbers.parse(f"+{number}")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
