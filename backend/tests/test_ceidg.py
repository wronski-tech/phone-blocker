from datetime import date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from phone_blocker import importer
from phone_blocker.db import make_sessionmaker
from phone_blocker.models import Organization, SourceState
from phone_blocker.sources import ceidg

THIS_MONTH = date.today().replace(day=1)
LAST_MONTH = (THIS_MONTH - timedelta(days=1)).replace(day=1)


def firm(firm_id, started, phone, status="AKTYWNY", name=None):
    return {"id": firm_id, "nazwa": name or f"Firma {firm_id}", "status": status, "telefon": phone,
            "dataRozpoczecia": started.isoformat(),
            "adresDzialalnosci": {"ulica": "ul. Długa", "budynek": "5", "lokal": "2", "miasto": "Wrocław",
                                  "kod": "50-001", "wojewodztwo": "DOLNOŚLĄSKIE"},
            "wlasciciel": {"nip": "1234563218", "regon": "123456785"}}


class FakeCeidg:
    """The documented API shapes, with a few businesses and a change feed."""

    def __init__(self):
        self.firms = {f["id"]: f for f in [
            firm("A1", LAST_MONTH, "+48 600 100 200"),
            firm("A2", LAST_MONTH, "brak"),  # no valid phone: left out
            firm("A3", LAST_MONTH, "71 777 11 22"),
            firm("B1", THIS_MONTH, "600100201"),
        ]}
        self.changed: list[str] = []
        self.requests: list[httpx.Request] = []
        self.fail_month: date | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["authorization"] == "Bearer token"
        params, path = request.url.params, request.url.path.rsplit("/", 1)[-1]
        if path == "firmy":
            start = date.fromisoformat(params["dataod"])
            if self.fail_month and start == self.fail_month:
                return httpx.Response(400)
            end = date.fromisoformat(params["datado"])
            found = [f for f in self.firms.values()
                     if f["status"] == "AKTYWNY" and start <= date.fromisoformat(f["dataRozpoczecia"]) <= end]
            page, size = int(params["page"]), int(params["limit"])
            chunk = found[page * size:(page + 1) * size]
            if not chunk:
                return httpx.Response(204)
            return httpx.Response(200, json={"firmy": [{"id": f["id"]} for f in chunk], "count": len(found)})
        if path == "firma":
            ids = [i.upper() for i in params.get_list("ids")]
            return httpx.Response(200, json={"firma": [self.firms[i] for i in ids if i in self.firms]})
        if path == "zmiana":
            ids, self.changed = self.changed, []
            if not ids:
                return httpx.Response(204)
            return httpx.Response(200, json={"identyfikatoryWpisow": ids, "count": len(ids)})
        return httpx.Response(404)


@pytest.fixture
def api(monkeypatch):
    fake = FakeCeidg()
    transport = httpx.MockTransport(fake.handler)
    real_client = httpx.Client
    monkeypatch.setattr(importer.httpx, "Client", lambda **kw: real_client(transport=transport, **kw))
    monkeypatch.setattr(ceidg, "FIRST_MONTH", LAST_MONTH)
    monkeypatch.setattr(ceidg, "PAGE_SIZE", 2)
    monkeypatch.setenv("CEIDG_TOKEN", "token")
    return fake


@pytest.fixture
def sessions(db_url):
    return make_sessionmaker(db_url)


def run(sessions):
    return importer.run_import(sessions, "ceidg", block_threshold=1, delay=0, log=lambda _: None)


def organizations(sessions):
    with sessions() as session:
        return {o.source_id: (o.name, [l.phone_number.number for l in o.listings])
                for o in session.scalars(select(Organization))}


def test_first_import_resumes_after_a_failure_then_follows_changes(api, sessions, monkeypatch):
    api.fail_month = THIS_MONTH
    failed = run(sessions)
    assert (failed.status, failed.saved) == ("failed", 2)  # last month's two firms with phones

    api.fail_month = None
    api.requests.clear()
    resumed = run(sessions)
    listed = {r.url.params["dataod"] for r in api.requests if r.url.path.endswith("/firmy")}
    assert (resumed.status, resumed.saved, listed) == ("success", 1, {THIS_MONTH.isoformat()})
    assert organizations(sessions) == {
        "A1": ("Firma A1", [48600100200]), "A3": ("Firma A3", [48717771122]), "B1": ("Firma B1", [48600100201]),
    }

    # A1 closes and B1 changes its phone; the change feed lists ids in lower case.
    api.firms["A1"]["status"] = "WYKRESLONY"
    api.firms["B1"]["telefon"] = "+48 600 999 888"
    api.changed = ["a1", "b1"]
    later = (datetime.now() + timedelta(hours=1)).replace(microsecond=0).isoformat(sep=" ")
    monkeypatch.setattr(ceidg, "_now", lambda: later)  # the next daily run
    changes = run(sessions)
    zmiana = [r.url.params for r in api.requests if r.url.path.endswith("/zmiana")]
    assert zmiana[-1]["datado"] == later

    assert (changes.status, changes.saved, changes.removed) == ("success", 1, 1)
    assert organizations(sessions) == {"A3": ("Firma A3", [48717771122]), "B1": ("Firma B1", [48600999888])}
    with sessions() as session:
        assert '"full_import_done": true' in session.get(SourceState, "ceidg").state


def test_needs_a_token(api, sessions, monkeypatch):
    monkeypatch.delenv("CEIDG_TOKEN")
    result = run(sessions)
    assert result.status == "failed" and "CEIDG_TOKEN" in result.message


def test_spaces_requests_and_waits_out_the_rate_limit_penalty(monkeypatch):
    clock = {"now": 1000.0}
    sleeps: list[float] = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(ceidg, "time", type("FakeTime", (), {
        "monotonic": staticmethod(lambda: clock["now"]), "sleep": staticmethod(sleep)}))
    responses = iter([httpx.Response(200, json={"n": 1}), httpx.Response(429), httpx.Response(200, json={"n": 2})])
    sent_at: list[float] = []

    def handler(request):
        sent_at.append(clock["now"])
        return next(responses)

    api = ceidg._Api(httpx.Client(transport=httpx.MockTransport(handler)), "token", delay=3.6)
    assert api.get("firmy", {}) == {"n": 1}
    assert api.get("firmy", {}) == {"n": 2}

    assert ceidg.PENALTY_SECONDS in sleeps
    assert all(b - a >= 3.6 for a, b in zip(sent_at, sent_at[1:]))
    assert sent_at[2] - sent_at[1] >= 180  # nothing sent while the API's block lasts
