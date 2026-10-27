import httpx

from phone_blocker.directory import ListedPhone
from phone_blocker.sources import ImportContext, nfz

HOSPITAL = "WOJEWÓDZKI SZPITAL SPECJALISTYCZNY WE WROCŁAWIU"


def row(provider, place, phone, address="UL. KAMIEŃSKIEGO 73A", code="010000123"):
    return {"attributes": {
        "provider": provider, "provider-code": code, "place": place, "address": address,
        "locality": "WROCŁAW", "phone": phone, "nip-provider": "8951581410", "regon-provider": "000293850",
    }}


ROWS = [
    row(HOSPITAL, "ODDZIAŁ KARDIOLOGII", "+48 71 327 01 41"),
    row(HOSPITAL, "PORADNIA NEUROLOGICZNA", "71 327 02 00"),
    # Same department again for another service, phone written differently.
    row(HOSPITAL, "ODDZIAŁ KARDIOLOGII", "(71) 327-01-41"),
    # Place named like the provider; a 7-digit number that is not a valid phone.
    row("NIEPUBLICZNY ZAKŁAD OPIEKI ZDROWOTNEJ PERIOMED", "NIEPUBLICZNY ZAKŁAD OPIEKI ZDROWOTNEJ PERIOMED",
        "600 146 580; 7794268", code="010000999"),
]


def test_groups_queue_rows_into_departments_with_phones(monkeypatch):
    monkeypatch.setattr(nfz, "PAGE_SIZE", 3)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        params = request.url.params
        if params["province"] != "01":
            return httpx.Response(200, json={"meta": {"count": 0}, "data": []})
        page = int(params["page"])
        return httpx.Response(200, json={"meta": {"count": len(ROWS)}, "data": ROWS[(page - 1) * 3:page * 3]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        records = dict(nfz.iter_records(ImportContext(delay=0, log=lambda _: None), client))

    assert len([r for r in requests if r.url.params["province"] == "01"]) == 2  # paginated
    assert [(r.name, r.phones) for r in records.values()] == [
        (HOSPITAL, [ListedPhone(48713270141, "phone", "ODDZIAŁ KARDIOLOGII")] * 2),
        (HOSPITAL, [ListedPhone(48713270200, "phone", "PORADNIA NEUROLOGICZNA")]),
        ("NZOZ PERIOMED", [ListedPhone(48600146580, "phone", None)]),
    ]
    first = next(iter(records.values()))
    assert (first.city, first.voivodeship, first.street) == ("WROCŁAW", "Dolnośląskie", "UL. KAMIEŃSKIEGO 73A")
