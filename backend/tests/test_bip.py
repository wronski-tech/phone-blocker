from pathlib import Path

from phone_blocker.directory import ListedPhone
from phone_blocker.sources.bip import parse_card

FIXTURE = Path(__file__).parent / "fixtures" / "bip_card_um_wroclaw.html"


def test_parse_card_reads_institution_and_all_numbers():
    card = parse_card(FIXTURE.read_text(), "https://www.gov.pl/web/bip/um-wroclaw")

    assert card.name == "Urząd Miejski Wrocławia"
    assert (card.street, card.postal_code, card.city) == ("Pl. Nowy Targ 1-8", "50-141", "Wrocław")
    assert (card.voivodeship, card.county, card.commune) == ("Dolnośląskie", "Wrocław", "Wrocław")
    assert card.website == "http://bip.um.wroc.pl"
    # The institution's e-mail, not the BIP editor's one listed further down.
    assert card.email == "kum@um.wroc.pl"
    assert (card.nip, card.regon) == ("8961003529", "001094670")
    assert card.phones == [
        ListedPhone(48717777777, "phone", None),
        ListedPhone(48717778655, "fax", None),
        ListedPhone(48717779061, "phone", "Redakcja BIP"),
        ListedPhone(48717778789, "fax", "Redakcja BIP"),
    ]
