"""Pharmacy register and RPWDL importers, with real rows from the registers' exports."""

import io
import zipfile
from pathlib import Path

import httpx
import pytest

from phone_blocker.directory import ListedPhone
from phone_blocker.phone import find_numbers
from phone_blocker.sources import ImportContext, apteki, rpwdl


@pytest.mark.parametrize(("text", "numbers"), [
    ("071 317-23-95  0606-795-234", [48713172395, 48606795234]),  # old trunk zero, spaces as separator
    ("(0-71) 123 45 67", [48711234567]),
    ("604 639 093", [48604639093]),  # a 0 inside the number is not a trunk zero
    ("74/8680242 74/8681513", [48748680242, 48748681513]),
    ("+48413341216 , 509649466", [48413341216, 48509649466]),
    ("22 451-48-53 wew. 25", [48224514853]),
    ("NULL", []),
])
def test_find_numbers_reads_register_formats(text, numbers):
    assert find_numbers(text) == numbers


def run(module, content: bytes) -> dict:
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content))) as client:
        return dict(module.iter_records(ImportContext(delay=0, log=lambda _: None), client))


def test_pharmacies_keep_active_ones_with_a_phone():
    records = run(apteki, (Path(__file__).parent / "fixtures" / "rejestr_aptek.xls").read_bytes())

    # 1000015 is inactive and 1014769 publishes no number.
    assert list(records) == ["1058988", "1000106"]
    named, outlet = records.values()
    assert (named.name, named.street, named.postal_code, named.city, named.voivodeship) == (
        "Apteka Słoneczna", "ul. Orzegowska 52 A", "41-907", "Bytom", "Śląskie")
    assert named.phones == [ListedPhone(48322819706, "phone"), ListedPhone(48322819706, "fax")]
    # Unnamed outlet: called after its owner, and no "ul." without a street name.
    assert (outlet.name, outlet.street) == ("PUNKT APTECZNY ROZALIA JAJEŚNICA", "107")
    assert outlet.phones == [ListedPhone(48413341216, "phone"), ListedPhone(48509649466, "phone")]


def csv_file(header: str, *rows: str) -> str:
    return "\r\n".join([header, *rows]) + "\r\n"


PROVIDERS = csv_file(
    '"ID Księgi";"NIP";"REGON";"Data wykreślenia z rejestru";"Data zakończenia działalności";"Nazwa";'
    '"Ulica";"Budynek";"Lokal";"Kod pocztowy";"Miejscowość";"Telefon";"Email";"Strona WWW"',
    '"10";"8951581410";"000293850";"NULL";"NULL";"WOJEWÓDZKI SZPITAL SPECJALISTYCZNY WE WROCŁAWIU";'
    '"Henryka Michała Kamieńskiego";"73";"A";"51-124";"Wrocław";"71 32 70 101";"NULL";"www.wssk.wroc.pl"',
    '"20";"NULL";"NULL";"NULL";"NULL";"NIEPUBLICZNY ZAKŁAD OPIEKI ZDROWOTNEJ ""MEDENT"" Iwona Antoniak";'
    '"Leśna";"1";"NULL";"00-001";"Warszawa";"NULL";"NULL";"NULL"',
    '"30";"NULL";"NULL";"2020-01-01";"NULL";"Zamknięta przychodnia";"NULL";"NULL";"NULL";"NULL";"NULL";'
    '"22 111 11 11";"NULL";"NULL"',
)
FACILITIES = csv_file(
    '"ID Księgi";"Nazwa";"Telefon";"Data zakończenia działalności"',
    '"10";"OŚRODEK SZPITALNYCH ŚWIADCZEŃ ZDROWOTNYCH";"071 327-02-02";"NULL"',
    '"10";"OŚRODEK AMBULATORYJNYCH ŚWIADCZEŃ ZDROWOTNYCH";"71 32 70 101";"NULL"',
    '"10";"ZAKŁAD SPRZĘTU ORTOPEDYCZNEGO";"71 327 09 99";"2020-12-31"',
    '"20";"NZOZ MEDENT";"22 222 22 22";"NULL"',
)
UNITS = csv_file(
    '"ID Księgi";"Nazwa";"Telefon";"Data zakończenia działalności JO"',
    '"10";"Wojewódzki Szpital Specjalistyczny we Wrocławiu";"71 327-02-02";"NULL"',
)
DEPARTMENTS = csv_file(
    '"ID Księgi";"Nazwa komórki";"Telefon";"Data zakończenia działalności komórki"',
    '"10";"Oddział kardiologii";"71 327 01 41";"NULL"',
    '"10";"Poradnia kardiologiczna";"71 327 01 41";"NULL"',
    '"10";"Poradnia medycyny pracy";"71 327 01 08";"NULL"',
    '"30";"Poradnia";"22 111 11 12";"NULL"',
)


def test_rpwdl_lists_providers_with_the_phones_of_their_units():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in [("podmioty.csv", PROVIDERS), ("zaklady.csv", FACILITIES), ("jednostki.csv", UNITS),
                           ("komorki.csv", DEPARTMENTS)]:
            archive.writestr(name, text.encode("utf-8"))

    records = run(rpwdl, buffer.getvalue())

    assert list(records) == ["10", "20"]  # the removed provider 30 is left out with its departments
    hospital, practice = records.values()
    assert (hospital.street, hospital.postal_code, hospital.city, hospital.website) == (
        "Henryka Michała Kamieńskiego 73/A", "51-124", "Wrocław", "www.wssk.wroc.pl")
    assert hospital.phones == [
        ListedPhone(48713270101, "phone"),  # the provider's own number, also listed by a facility
        ListedPhone(48713270202, "phone", "OŚRODEK SZPITALNYCH ŚWIADCZEŃ ZDROWOTNYCH"),  # highest level wins
        ListedPhone(48713270141, "phone"),  # shared by two departments: no department name
        ListedPhone(48713270108, "phone", "Poradnia medycyny pracy"),
    ]
    assert (practice.name, practice.phones) == ('NZOZ "MEDENT" Iwona Antoniak',
                                                [ListedPhone(48222222222, "phone", "NZOZ MEDENT")])
