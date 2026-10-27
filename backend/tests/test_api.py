import pytest
from fastapi.testclient import TestClient

from phone_blocker.api import create_app
from phone_blocker.bip import Card, CardPhone, save_card
from phone_blocker.config import Settings
from phone_blocker.db import make_sessionmaker

TOKEN = "secret"
SPAMMER = "+48 500 100 200"
SPAMMER_INT = 48500100200
CITY_HALL = 48717777777


@pytest.fixture
def client(db_url):
    app = create_app(Settings(database_url=db_url, api_token=TOKEN))
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as c:
        yield c


def save_city_hall(db_url, name="Urząd Miejski Wrocławia", phones=None):
    phones = phones or [CardPhone(CITY_HALL, "phone", None), CardPhone(48717779061, "phone", "Redakcja BIP")]
    sessions = make_sessionmaker(db_url)
    with sessions.begin() as session:
        save_card(session, "https://www.gov.pl/web/bip/um-wroclaw",
                  Card(name=name, city="Wrocław", phones=phones), block_threshold=1)


def directory(client, since=0, **params):
    response = client.get("/v1/directory", params={"since": since, **params})
    assert response.status_code == 200
    return response.json()


def test_requires_token(client):
    assert client.get("/v1/directory", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_report_blocks_number_and_safe_report_unblocks_it_in_sync(client):
    response = client.post("/v1/reports", json={"number": SPAMMER, "category": "telemarketing", "comment": "OZE"})
    assert response.status_code == 201
    assert response.json()["blocked"] is True
    assert response.json()["label"] == "Spam: Telemarketing (1)"

    full = directory(client)
    assert full["entries"] == [{"number": SPAMMER_INT, "label": "Spam: Telemarketing (1)", "blocked": True}]

    client.post("/v1/reports", json={"number": "500100200", "category": "safe"})

    # The phone sees the change as a removal, and fresh installs no longer get the number.
    delta = directory(client, since=full["next_since"])
    assert delta["entries"] == [{"number": SPAMMER_INT, "label": None, "blocked": False}]
    assert directory(client)["entries"] == []

    lookup = client.get(f"/v1/numbers/{SPAMMER}").json()
    assert lookup["reports"]["spam"] == 1
    assert lookup["reports"]["safe"] == 1
    assert lookup["reports"]["recent"][-1]["comment"] == "OZE"


def test_public_number_is_labelled_and_never_blocked(client, db_url):
    save_city_hall(db_url)
    client.post("/v1/reports", json={"number": "71 777 77 77", "category": "scam"})

    lookup = client.get("/v1/numbers/+48717777777").json()
    assert lookup["label"] == "Urząd Miejski Wrocławia"
    assert lookup["blocked"] is False
    assert lookup["listings"][0]["organization"]["city"] == "Wrocław"

    entries = {e["number"]: e for e in directory(client)["entries"]}
    assert entries[48717779061]["label"] == "Urząd Miejski Wrocławia – Redakcja BIP"


def test_reimported_card_updates_labels_and_removes_dropped_numbers(client, db_url):
    save_city_hall(db_url)
    before = directory(client)

    save_city_hall(db_url, name="Urząd Miejski Wrocławia (UMW)", phones=[CardPhone(CITY_HALL, "phone", None)])

    delta = {e["number"]: e for e in directory(client, since=before["next_since"])["entries"]}
    assert delta == {
        CITY_HALL: {"number": CITY_HALL, "label": "Urząd Miejski Wrocławia (UMW)", "blocked": False},
        48717779061: {"number": 48717779061, "label": None, "blocked": False},
    }


def test_directory_pages_by_version(client):
    for number in ("500100200", "500100201", "500100202"):
        client.post("/v1/reports", json={"number": number, "category": "scam"})

    first = directory(client, limit=2)
    second = directory(client, since=first["next_since"], limit=2)

    assert first["has_more"] is True and second["has_more"] is False
    numbers = [e["number"] for e in first["entries"] + second["entries"]]
    assert numbers == [48500100200, 48500100201, 48500100202]


def test_search_ignores_case_and_polish_diacritics(client, db_url):
    save_city_hall(db_url)

    results = client.get("/v1/organizations", params={"q": "URZAD wroclaw"}).json()

    assert [r["name"] for r in results] == ["Urząd Miejski Wrocławia"]
    assert results[0]["phones"][0]["formatted"] == "+48 71 777 77 77"
    assert client.get("/v1/organizations", params={"q": "gdansk"}).json() == []


def test_lookup_validates_numbers(client):
    unknown = client.get("/v1/numbers/+48600700800")
    assert unknown.status_code == 200
    assert unknown.json()["label"] is None and unknown.json()["listings"] == []
    assert client.get("/v1/numbers/123").status_code == 422
