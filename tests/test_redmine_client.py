import json

import httpx
import pytest
import respx

from src.redmine_client import RedmineClient, RedmineError

BASE = "https://redmine.example.com"


def make_client() -> RedmineClient:
    return RedmineClient(base_url=BASE, api_key="key")


def test_init_requires_config():
    with pytest.raises(RedmineError):
        RedmineClient(base_url="", api_key="")


def test_init_rejects_bad_scheme():
    with pytest.raises(RedmineError) as exc_info:
        RedmineClient(base_url="ftp://redmine.example.com", api_key="k")
    assert "http" in exc_info.value.message.lower()


def test_init_allows_http_for_intranet():
    client = RedmineClient(base_url="http://intranet/redmine/", api_key="k")
    assert client.base_url == "http://intranet/redmine"


def test_auth_header():
    client = make_client()
    assert client._headers["X-Redmine-API-Key"] == "key"


@respx.mock
def test_current_user():
    respx.get(f"{BASE}/users/current.json").mock(
        return_value=httpx.Response(
            200, json={"user": {"id": 7, "firstname": "Ana", "lastname": "Lima"}}
        )
    )
    user = make_client().current_user()
    assert user["id"] == 7


@respx.mock
def test_search_issues_passes_params():
    route = respx.get(f"{BASE}/issues.json").mock(
        return_value=httpx.Response(200, json={"issues": [{"id": 12, "subject": "x"}]})
    )
    data = make_client().search_issues({"assigned_to_id": "me", "limit": 5})
    assert data["issues"][0]["id"] == 12
    params = route.calls.last.request.url.params
    assert params["assigned_to_id"] == "me"
    assert params["limit"] == "5"


@respx.mock
def test_log_time_sends_time_entry():
    route = respx.post(f"{BASE}/time_entries.json").mock(
        return_value=httpx.Response(201, json={"time_entry": {"id": 99}})
    )
    result = make_client().log_time("12", 2.5, "2026-06-10", activity_id=8, comments="dev")
    assert result["id"] == 99
    body = json.loads(route.calls.last.request.content)["time_entry"]
    assert body["issue_id"] == "12"
    assert body["hours"] == 2.5
    assert body["spent_on"] == "2026-06-10"
    assert body["activity_id"] == 8
    assert body["comments"] == "dev"


@respx.mock
def test_log_time_omits_activity_when_none():
    route = respx.post(f"{BASE}/time_entries.json").mock(
        return_value=httpx.Response(201, json={"time_entry": {"id": 1}})
    )
    make_client().log_time("12", 1.0, "2026-06-10")
    body = json.loads(route.calls.last.request.content)["time_entry"]
    assert "activity_id" not in body
    assert "comments" not in body


@respx.mock
def test_add_note_puts_notes_only():
    route = respx.put(f"{BASE}/issues/12.json").mock(return_value=httpx.Response(204))
    make_client().add_note("12", "hello")
    body = json.loads(route.calls.last.request.content)
    assert body == {"issue": {"notes": "hello"}}


@respx.mock
def test_get_time_entries():
    respx.get(f"{BASE}/time_entries.json").mock(
        return_value=httpx.Response(200, json={"time_entries": [{"id": 3, "hours": 2.0}]})
    )
    data = make_client().get_time_entries("12")
    assert data["time_entries"][0]["id"] == 3


@respx.mock
def test_network_error_becomes_redmine_error():
    respx.get(f"{BASE}/users/current.json").mock(side_effect=httpx.ConnectError("offline"))
    with pytest.raises(RedmineError) as exc_info:
        make_client().current_user()
    assert "network" in exc_info.value.message.lower()


@respx.mock
def test_422_maps_to_friendly_message():
    respx.post(f"{BASE}/time_entries.json").mock(
        return_value=httpx.Response(422, json={"errors": ["Activity cannot be blank"]})
    )
    with pytest.raises(RedmineError) as exc_info:
        make_client().log_time("12", 1.0, "2026-06-10")
    assert exc_info.value.status == 422
    assert "activity cannot be blank" in (exc_info.value.detail or "").lower()
