import httpx
import pytest
from fastapi.testclient import TestClient

from phone_blocker.api import create_app
from phone_blocker.config import Settings
from phone_blocker.db import make_sessionmaker
from phone_blocker.sources import ImportContext, uke

# Real rows from the UKE exports; each table has its own column order.
TABLES = {
    "pstn": "Strefa (AB);Zakres (number);Operator (nazwa);Operator (ID);Strefa (nazwa);Strefa (symbol);"
            "Obszar numeracyjny;Data modyfikacji\r\n"
            "71;7177(0,6);Netia S.A.;6;WROCŁAW;SN-WR;CAŁA SN;2020-04-30 12:15\r\n"
            "71;7177(5,9);Rezerwa Prezesa UKE;99990;WROCŁAW;SN-WR;CAŁA SN;2015-07-20 01:04\r\n",
    "plmn": "Zakres (number);Operator (ID);Operator (nazwa);Data modyfikacji\r\n"
            "500;1;Orange Polska S.A.;2015-07-20 12:36\r\n",
    "voip": "Zakres (number);Operator (nazwa);Operator (ID);Data modyfikacji\r\n"
            "391069;Polkomtel Sp. z o.o.;3;2015-07-20 01:14\r\n",
    "ndin": "Zakres (number);Operator (nazwa);Operator (ID);Nazwa typu usługi;Data modyfikacji\r\n"
            "800000;EXATEL S.A.;18;FPH usługa połączenia bezpłatnego (freephone);2015-07-20 01:15\r\n",
}


def test_expand_range_notation():
    assert uke.expand("4500") == ["4500"]
    assert uke.expand("121(0,3-5)") == ["1210", "1213", "1214", "1215"]


@pytest.fixture
def client(db_url):
    def handler(request: httpx.Request) -> httpx.Response:
        table = request.url.path.split("/")[2].removesuffix("_tables")
        return httpx.Response(200, content=TABLES[table].encode("cp1250"))

    sessions = make_sessionmaker(db_url)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http, sessions.begin() as session:
        assert uke.replace_all(session, http, ImportContext(delay=0, log=lambda _: None)) == 7  # 2 + 2 + 1 + 1 + 1 prefixes
    with TestClient(create_app(Settings(database_url=db_url))) as c:
        yield c


@pytest.mark.parametrize(("number", "expected"), [
    ("71 770 55 55", {"type": "fixed_line", "region": "Wrocław", "operator": "Netia S.A.", "service": None,
                      "allocated": True}),
    # Same block, but the 71775 part is a UKE reserve: nobody should be calling from it.
    ("71 775 55 55", {"type": "fixed_line", "region": "Wrocław", "operator": None, "service": None,
                      "allocated": False}),
    ("500 100 200", {"type": "mobile", "region": "Polska", "operator": "Orange Polska S.A.", "service": None,
                     "allocated": True}),
    ("800 000 123", {"type": "toll_free", "region": "Polska", "operator": "EXATEL S.A.",
                     "service": "FPH usługa połączenia bezpłatnego (freephone)", "allocated": True}),
    ("+49 30 1234567", {"type": "fixed_line", "region": "Berlin", "operator": None, "service": None,
                        "allocated": None}),
])
def test_lookup_describes_any_number(client, number, expected):
    assert client.get(f"/v1/numbers/{number}").json()["info"] == expected


def test_unassigned_numbers_are_blocked_unless_an_allow_rule_covers_them(client):
    def lookup(number):
        body = client.get(f"/v1/numbers/{number}").json()
        return body["blocked"], body["label"]

    assert lookup("71 775 55 55") == (True, "Numer nieprzydzielony (podszywanie?)")
    assert lookup("71 770 55 55") == (False, None)
    assert lookup("+49 30 1234567") == (False, None)  # not in the UKE tables: unknown, not unassigned

    client.post("/v1/rules", json={"prefix": "+48", "action": "allow", "note": "Trust caller ID"})
    assert lookup("71 775 55 55") == (False, None)
