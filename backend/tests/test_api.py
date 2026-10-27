import pytest
from fastapi.testclient import TestClient

from phone_blocker.api import create_app
from phone_blocker.config import Settings
from phone_blocker.db import make_sessionmaker
from phone_blocker.directory import ListedPhone, OrganizationRecord, save_record

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
    phones = phones or [ListedPhone(CITY_HALL, "phone", None), ListedPhone(48717779061, "phone", "Redakcja BIP")]
    sessions = make_sessionmaker(db_url)
    with sessions.begin() as session:
        record = OrganizationRecord("https://www.gov.pl/web/bip/um-wroclaw", name, city="Wrocław", phones=phones)
        save_record(session, "bip", record, block_threshold=1)


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

    save_city_hall(db_url, name="Urząd Miejski Wrocławia (UMW)", phones=[ListedPhone(CITY_HALL, "phone", None)])

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


def test_directory_download_is_gzipped(client):
    for n in range(30):
        client.post("/v1/reports", json={"number": f"5001002{n:02d}", "category": "scam"})

    response = client.get("/v1/directory", headers={"Accept-Encoding": "gzip"})

    assert response.headers["content-encoding"] == "gzip"
    assert len(response.json()["entries"]) == 30


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


def test_personal_block_beats_public_listing_and_clears(client, db_url):
    save_city_hall(db_url)
    before = directory(client)["next_since"]

    blocked = client.put(f"/v1/numbers/{CITY_HALL}/personal", json={"action": "block"}).json()
    assert (blocked["blocked"], blocked["label"]) == (True, "Urząd Miejski Wrocławia")
    assert directory(client, since=before)["entries"] == [
        {"number": CITY_HALL, "label": "Urząd Miejski Wrocławia", "blocked": True}]

    cleared = client.put(f"/v1/numbers/{CITY_HALL}/personal", json={"action": None, "label": None}).json()
    assert cleared["blocked"] is False
    assert client.get("/v1/personal").json() == []


def test_personal_allow_overrides_spam_reports_and_label_shows(client):
    client.post("/v1/reports", json={"number": SPAMMER, "category": "scam"})

    allowed = client.put(f"/v1/numbers/{SPAMMER}/personal", json={"action": "allow", "label": " Dr Nowak "}).json()
    assert (allowed["blocked"], allowed["label"]) == (False, "Dr Nowak")

    # Removing only the label keeps the number allowed, without the spam label coming back.
    allowed = client.put(f"/v1/numbers/{SPAMMER}/personal", json={"action": "allow"}).json()
    assert (allowed["blocked"], allowed["label"]) == (False, None)
    assert client.get("/v1/personal").json() == [
        {"number": SPAMMER_INT, "formatted": "+48 500 100 200", "action": "allow", "label": None}]


def test_deleting_a_report_undoes_its_effect(client):
    report_id = client.post("/v1/reports", json={"number": SPAMMER, "category": "scam"}).json()["reports"]["recent"][0]["id"]
    assert client.get(f"/v1/numbers/{SPAMMER}").json()["blocked"] is True

    assert client.delete(f"/v1/reports/{report_id}").status_code == 204

    number = client.get(f"/v1/numbers/{SPAMMER}").json()
    assert (number["blocked"], number["label"], number["reports"]["total"]) == (False, None, 0)
    assert client.delete(f"/v1/reports/{report_id}").status_code == 404


def test_rules_block_or_allow_prefixes_at_lookup(client, db_url):
    save_city_hall(db_url)
    assert client.post("/v1/rules", json={"prefix": "+44", "action": "block"}).status_code == 201
    allow = client.post("/v1/rules", json={"prefix": "0044 20 7946", "action": "allow", "note": "London office"}).json()
    client.post("/v1/rules", json={"prefix": "+48 71", "action": "block", "note": "Wrocław spam"})

    def lookup(number):
        body = client.get(f"/v1/numbers/{number}").json()
        return body["blocked"], body["label"], body["rule"] and body["rule"]["formatted"]

    # The longest matching prefix wins, in either direction.
    assert lookup("+44 161 496 0000") == (True, "Reguła +44", "+44")
    assert lookup("+44 20 7946 0958") == (False, None, "+44 20 7946")
    assert lookup("71 333 22 11") == (True, "Wrocław spam", "+48 71")
    # Public listings and personal settings beat rules; numbers outside every rule are untouched.
    assert lookup(CITY_HALL) == (False, "Urząd Miejski Wrocławia", "+48 71")
    client.put("/v1/numbers/+44 161 496 0000/personal", json={"action": "allow"})
    assert lookup("+44 161 496 0000") == (False, None, "+44")
    assert lookup(SPAMMER) == (False, None, None)
    # An allow rule doesn't cancel spam reports.
    client.post("/v1/rules", json={"prefix": "+48 500", "action": "allow"})
    assert client.post("/v1/reports", json={"number": SPAMMER, "category": "scam"}).json()["blocked"] is True

    # Rules reach the phone through /v1/rules, not as millions of directory entries.
    assert {e["number"] for e in directory(client)["entries"]} == {CITY_HALL, 48717779061, SPAMMER_INT}

    # Saving a prefix again replaces its rule; deleting it lifts the block.
    replaced = client.post("/v1/rules", json={"prefix": "+4420 7946", "action": "block"}).json()
    rules = client.get("/v1/rules").json()
    assert [(r["formatted"], r["action"], r["note"]) for r in rules] == [
        ("+44", "block", None), ("+44 20 7946", "block", None), ("+48 500", "allow", None),
        ("+48 71", "block", "Wrocław spam")]
    assert replaced["id"] == allow["id"]
    assert client.delete(f"/v1/rules/{rules[3]['id']}").status_code == 204
    assert lookup("71 333 22 11") == (False, None, None)
    assert client.delete(f"/v1/rules/{rules[3]['id']}").status_code == 404


@pytest.mark.parametrize("prefix", ["44 70", "+", "+0 22", "+999", "+44 7x", "+48 1234567890123456"])
def test_rule_prefix_needs_a_country_code(client, prefix):
    assert client.post("/v1/rules", json={"prefix": prefix, "action": "block"}).status_code == 422
