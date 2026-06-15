import json

import httpx
import pytest
import respx

from src.artia_client import ArtiaClient, ArtiaError

BASE = "https://api.artia.com/graphql"


def make_client() -> ArtiaClient:
    return ArtiaClient(client_id="client", secret="secret", base_url=BASE)


def _graphql_query(request: httpx.Request) -> str:
    body = json.loads(request.content)
    return body["query"]


def _graphql_response(request: httpx.Request) -> httpx.Response:
    query = _graphql_query(request)
    if "authenticationByClient" in query:
        return httpx.Response(200, json={"data": {"authenticationByClient": {"token": "token-1"}}})
    if "query Account" in query:
        return httpx.Response(200, json={"data": {"me": {"id": "acct-1", "displayName": "Ana"}}})
    if "ListActivities" in query:
        return httpx.Response(
            200,
            json={
                "data": {
                    "activities": {
                        "items": [
                            {
                                "id": "55",
                                "title": "Fix bug",
                                "status": "Open",
                                "url": "https://example.com/a/55",
                                "responsible": {"id": "acct-1", "displayName": "Ana"},
                                "categories": [{"name": "bug"}],
                            }
                        ]
                    }
                }
            },
        )
    if "GetActivity" in query:
        return httpx.Response(
            200,
            json={
                "data": {
                    "activity": {
                        "id": "55",
                        "title": "Fix bug",
                        "status": "Open",
                        "description": "details",
                        "url": "https://example.com/a/55",
                        "responsible": {"id": "acct-1", "displayName": "Ana"},
                        "categories": [{"name": "bug"}],
                    }
                }
            },
        )
    if "ListTimeEntries" in query:
        return httpx.Response(
            200,
            json={
                "data": {
                    "timeEntries": {
                        "items": [
                            {
                                "id": "te-1",
                                "dateAt": "2026-06-14",
                                "startTime": "09:30",
                                "duration": 5400,
                                "comment": "tracked",
                                "author": {"id": "acct-1", "displayName": "Ana"},
                            }
                        ]
                    }
                }
            },
        )
    if "CreateTimeEntry" in query:
        return httpx.Response(
            200,
            json={
                "data": {
                    "createTimeEntry": {
                        "id": "te-2",
                        "dateAt": "2026-06-14",
                        "startTime": "10:00",
                        "duration": 1800,
                    }
                }
            },
        )
    return httpx.Response(200, json={"data": {}})


def test_requires_credentials():
    with pytest.raises(ArtiaError):
        ArtiaClient(client_id="", secret="", base_url=BASE)


def test_rejects_non_http_scheme():
    with pytest.raises(ArtiaError):
        ArtiaClient(client_id="c", secret="s", base_url="ftp://api.artia.com/graphql")


def test_strips_trailing_slash():
    assert make_client().base_url == BASE
    assert ArtiaClient(client_id="c", secret="s", base_url=f"{BASE}/").base_url == BASE


def test_normalizes_host_only_url_to_graphql_endpoint():
    assert (
        ArtiaClient(client_id="c", secret="s", base_url="https://api.artia.com/").base_url
        == BASE
    )


@respx.mock
def test_authenticates_and_sends_bearer_header():
    route = respx.post(BASE).mock(side_effect=_graphql_response)
    make_client().account()
    auth_call = route.calls[0].request
    data_call = route.calls[1].request
    assert "authenticationByClient" in _graphql_query(auth_call)
    assert auth_call.headers.get("Authorization") is None
    assert data_call.headers["Authorization"] == "Bearer token-1"


@respx.mock
def test_list_activities_sends_folder_and_query():
    route = respx.post(BASE).mock(side_effect=_graphql_response)
    tasks = make_client().list_activities("folder-9", 5, query="login")
    body = json.loads(route.calls.last.request.content)
    assert "ListActivities" in body["query"]
    assert body["variables"]["folderId"] == "folder-9"
    assert body["variables"]["limit"] == 5
    assert body["variables"]["query"] == "login"
    assert tasks[0]["id"] == "55"


@respx.mock
def test_get_activity_sends_account_and_activity_ids():
    route = respx.post(BASE).mock(side_effect=_graphql_response)
    item = make_client().get_activity("acct-1", "55")
    body = json.loads(route.calls.last.request.content)
    assert "GetActivity" in body["query"]
    assert body["variables"]["accountId"] == "acct-1"
    assert body["variables"]["activityId"] == "55"
    assert item["id"] == "55"


@respx.mock
def test_list_time_entries_sends_account_and_activity_ids():
    route = respx.post(BASE).mock(side_effect=_graphql_response)
    rows = make_client().list_time_entries("acct-1", "55")
    body = json.loads(route.calls.last.request.content)
    assert "ListTimeEntries" in body["query"]
    assert body["variables"]["accountId"] == "acct-1"
    assert body["variables"]["activityId"] == "55"
    assert rows[0]["id"] == "te-1"


@respx.mock
def test_create_time_entry_sends_fields_and_returns_payload():
    route = respx.post(BASE).mock(side_effect=_graphql_response)
    row = make_client().create_time_entry(
        "acct-1",
        "55",
        "2026-06-14",
        "10:00",
        1800,
        "status-1",
    )
    body = json.loads(route.calls.last.request.content)
    assert "CreateTimeEntry" in body["query"]
    assert body["variables"]["accountId"] == "acct-1"
    assert body["variables"]["activityId"] == "55"
    assert body["variables"]["dateAt"] == "2026-06-14"
    assert body["variables"]["startTime"] == "10:00"
    assert body["variables"]["duration"] == 1800
    assert body["variables"]["statusId"] == "status-1"
    assert row["id"] == "te-2"


@respx.mock
def test_graphql_errors_become_friendly_error():
    respx.post(BASE).mock(return_value=httpx.Response(200, json={"errors": [{"message": "boom"}]}))
    with pytest.raises(ArtiaError) as exc_info:
        make_client().account()
    assert "boom" in exc_info.value.detail.lower()


@respx.mock
def test_reauthenticates_on_401_once():
    calls = {"query": 0, "auth": 0}

    def side_effect(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "authenticationByClient" in body["query"]:
            calls["auth"] += 1
            token = "token-2"
            return httpx.Response(200, json={"data": {"authenticationByClient": {"token": token}}})
        calls["query"] += 1
        if calls["query"] == 1:
            return httpx.Response(401, json={"message": "expired"})
        return httpx.Response(200, json={"data": {"me": {"id": "acct-1", "displayName": "Ana"}}})

    route = respx.post(BASE).mock(side_effect=side_effect)
    client = make_client()
    client._token = "expired"
    account = client.account()
    assert account["id"] == "acct-1"
    assert route.calls[-1].request.headers["Authorization"] == "Bearer token-2"


@respx.mock
def test_network_failure_is_wrapped_after_retry(monkeypatch):
    route = respx.post(BASE).mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json={"data": {"me": {"id": "acct-1"}}})]
    )
    sleeps: list[float] = []
    monkeypatch.setattr("src.artia_client.time.sleep", lambda value: sleeps.append(value))
    client = make_client()
    client._token = "token-1"
    data = client.account()
    assert data["id"] == "acct-1"
    assert sleeps == [0.5]
    assert route.call_count == 2