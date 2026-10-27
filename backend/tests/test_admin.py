import pytest
from fastapi.testclient import TestClient

from phone_blocker.api import create_app
from phone_blocker.config import Settings
from phone_blocker.db import make_sessionmaker
from phone_blocker.directory import ListedPhone, OrganizationRecord, save_record

TOKEN = "secret"
SAME_ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture
def client(db_url):
    app = create_app(Settings(database_url=db_url, api_token=TOKEN))
    with TestClient(app, follow_redirects=False) as c:
        c.auth = ("admin", TOKEN)
        yield c


def api(client, method, path, **kwargs):
    return client.request(method, path, headers={"Authorization": f"Bearer {TOKEN}"}, auth=None, **kwargs)


def test_requires_the_api_token_as_password(client):
    assert client.get("/admin", auth=None).status_code == 401
    assert client.get("/admin", auth=None).headers["www-authenticate"].startswith("Basic")
    assert client.get("/admin", auth=("admin", "wrong")).status_code == 401
    assert client.get("/admin").status_code == 200


def test_refuses_forms_posted_from_other_sites(client):
    api(client, "POST", "/v1/reports", json={"number": "500100200", "category": "scam"})

    for headers in ({"Origin": "https://evil.example"}, {}):
        response = client.post("/admin/numbers/48500100200/personal", data={"action": "allow"}, headers=headers)
        assert response.status_code == 403
    assert api(client, "GET", "/v1/numbers/500100200").json()["blocked"] is True


def test_fix_a_number_and_undo_a_report(client):
    report_id = api(client, "POST", "/v1/reports", json={"number": "500100200", "category": "scam",
                                                         "comment": "Fake bank"}).json()["reports"]["recent"][0]["id"]
    page = client.get("/admin/numbers/48500100200").text
    assert "Fake bank" in page and "Spam: Oszustwo (1)" in page

    response = client.post("/admin/numbers/48500100200/personal", data={"action": "allow", "label": "Bank Pekao"},
                           headers=SAME_ORIGIN)
    assert (response.status_code, response.headers["location"]) == (303, "/admin/numbers/48500100200")
    number = api(client, "GET", "/v1/numbers/500100200").json()
    assert (number["blocked"], number["label"]) == (False, "Bank Pekao")

    client.post(f"/admin/reports/{report_id}/delete", data={"back": "/admin/reports"}, headers=SAME_ORIGIN)
    assert api(client, "GET", "/v1/numbers/500100200").json()["reports"]["total"] == 0


def test_search_goes_to_a_number_or_lists_organizations(client, db_url):
    with make_sessionmaker(db_url).begin() as session:
        save_record(session, "bip", OrganizationRecord("https://www.gov.pl/web/bip/um", "Urząd Miejski Wrocławia",
                                                       city="Wrocław", phones=[ListedPhone(48717777777, "phone")]),
                    block_threshold=1)

    assert client.get("/admin/search", params={"q": "71 777 77 77"}).headers["location"] == "/admin/numbers/48717777777"
    page = client.get("/admin/search", params={"q": "urzad wroclaw"}).text
    assert "Urząd Miejski Wrocławia" in page and "+48 71 777 77 77" in page
