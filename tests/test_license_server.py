"""Finding the licence server through evzero.org/clipped/api.json."""

import httpx
import pytest

from clipped.services import license_server as ls

pytestmark = pytest.mark.unlicensed


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(ls, "OVERRIDE", "")
    monkeypatch.setattr(ls, "SITE", "https://evzero.org")
    ls.forget()
    yield
    ls.forget()


def site(api_json, calls=None, server_status=200):
    """A transport standing in for evzero.org (api.json) and the licence server it points at."""
    def handle(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        if request.url.host == "evzero.org" and request.url.path == "/clipped/api.json":
            if isinstance(api_json, Exception):
                raise api_json
            return httpx.Response(200, json=api_json)
        if request.url.host == "licence.example.org":
            if server_status != 200:
                return httpx.Response(server_status, text="<html>not here</html>")
            return httpx.Response(200, json={"plan": "day", "path": request.url.path})
        return httpx.Response(404)
    return httpx.MockTransport(handle)


def test_the_app_asks_evzero_where_the_server_is_and_remembers():
    calls = []
    t = site({"api": "https://licence.example.org/clipped/"}, calls)
    assert ls.activate("CLIP-X", "0123456789abcdef", transport=t)["path"] == "/clipped/activate/"
    ls.activate("CLIP-X", "0123456789abcdef", transport=t)
    assert sum("api.json" in c for c in calls) == 1  # looked up once, then remembered


def test_not_switched_on_yet_says_so():
    with pytest.raises(ls.LicenseServerError) as err:
        ls.server(site({"api": ""}))
    assert err.value.code == "not_live"


@pytest.mark.parametrize("api", ["http://licence.example.org/clipped", "javascript:alert(1)", "https://", "ftp://x.org",
                                 "https://licence.example.org/clipped?x=1", "https://user@evil.org/clipped"])
def test_only_https_addresses_are_trusted(api):
    with pytest.raises(ls.LicenseServerError) as err:
        ls.server(site({"api": api}))
    assert err.value.code == "not_live"


def test_offline_first_time_is_offline_but_a_known_address_keeps_working(monkeypatch):
    with pytest.raises(ls.LicenseServerError) as err:
        ls.server(site(httpx.ConnectError("no internet")))
    assert err.value.code == "offline"
    assert ls.server(site({"api": "https://licence.example.org/clipped"})) == "https://licence.example.org/clipped"
    monkeypatch.setattr(ls, "LOOKUP_TTL", -1)  # time to look again, but evzero.org is down: keep the last answer
    assert ls.server(site(httpx.ConnectError("no internet"))) == "https://licence.example.org/clipped"


def test_a_server_that_moved_is_looked_up_again():
    calls = []
    t = site({"api": "https://licence.example.org/clipped"}, calls, server_status=404)
    with pytest.raises(ls.LicenseServerError) as err:
        ls.pickup("a" * 32, transport=t)
    assert err.value.status == 404
    ls.server(t)
    assert sum("api.json" in c for c in calls) == 2


def test_the_override_skips_the_lookup(monkeypatch):
    monkeypatch.setattr(ls, "OVERRIDE", "http://127.0.0.1:8899/api/clipped")
    assert ls.server(site(httpx.ConnectError("never asked"))) == "http://127.0.0.1:8899/api/clipped"
