import json

import httpx
import pytest
import respx

from src.artia_client import ArtiaClient
from src.errors import ArtiaError
from src.providers.artia_provider import ArtiaProvider
from src.services.provider_registry import registry

BASE = "https://api.artia.com/graphql"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ARTIA_CLIENT_ID", "client")
    monkeypatch.setenv("ARTIA_SECRET", "secret")
    monkeypatch.setenv("ARTIA_ACCOUNT_ID", "acct-1")
    monkeypatch.setenv("ARTIA_FOLDER_ID", "folder-9")
    monkeypatch.setenv("ARTIA_API_URL", BASE)
    registry.reset()


def make_provider(folder_id: str = "folder-9") -> ArtiaProvider:
    return ArtiaProvider(ArtiaClient(client_id="client", secret="secret", base_url=BASE), "acct-1", folder_id)


def _graphql_response(request: httpx.Request) -> httpx.Response:
    body = request.read().decode()
    if "authenticationByClient" in body:
        return httpx.Response(200, json={"data": {"authenticationByClient": {"token": "token-1"}}})
    if "query Account" in body:
        return httpx.Response(200, json={"data": {"me": {"id": "acct-1", "displayName": "Ana Lima"}}})
    if "ListActivities" in body:
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
                                "description": "details",
                                "url": "https://example.com/a/55",
                                "responsible": {"id": "acct-1", "displayName": "Ana Lima"},
                                "categories": [{"name": "bug"}],
                            },
                            {
                                "id": "56",
                                "title": "Other",
                                "status": "Open",
                                "responsible": {"id": "someone-else", "displayName": "Other"},
                            },
                        ]
                    }
                }
            },
        )
    if "GetActivity" in body:
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
                        "responsible": {"id": "acct-1", "displayName": "Ana Lima"},
                        "categories": [{"name": "bug"}],
                    }
                }
            },
        )
    if "ListTimeEntries" in body:
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
                                "author": {"id": "acct-1", "displayName": "Ana Lima"},
                            }
                        ]
                    }
                }
            },
        )
    if "CreateTimeEntry" in body:
        return httpx.Response(
            200,
            json={
                "data": {
                    "createTimeEntry": {
                        "id": "te-2",
                        "dateAt": "2026-06-14",
                        "startTime": "08:45",
                        "duration": 3600,
                    }
                }
            },
        )
    return httpx.Response(200, json={"data": {}})


@respx.mock
def test_whoami_builds_identity():
    respx.post(BASE).mock(side_effect=_graphql_response)
    out = make_provider().whoami()
    assert out["provider"] == "artia"
    assert out["ok"] is True
    assert out["accountId"] == "acct-1"
    assert out["displayName"] == "Ana Lima"


@respx.mock
def test_search_default_uses_folder_and_filters_assigned_to_me():
    respx.post(BASE).mock(side_effect=_graphql_response)
    tasks = make_provider().search_tasks()
    assert tasks[0].id == "55"
    assert tasks[0].summary == "Fix bug"
    assert tasks[0].status == "Open"
    assert tasks[0].labels == ["bug"]


def test_search_without_folder_raises():
    with pytest.raises(ArtiaError):
        make_provider(folder_id="").search_tasks()


@respx.mock
def test_get_task_maps_fields_and_url():
    respx.post(BASE).mock(side_effect=_graphql_response)
    task = make_provider().get_task("55")
    assert task.id == "55"
    assert task.summary == "Fix bug"
    assert task.status == "Open"
    assert task.description == "details"
    assert task.url == "https://example.com/a/55"


def test_capabilities_disable_optional_features():
    provider = make_provider()
    assert provider.capabilities.supports_comments is False
    assert provider.capabilities.supports_worklogs is True


@respx.mock
def test_get_worklogs_maps_entries():
    respx.post(BASE).mock(side_effect=_graphql_response)
    rows = make_provider().get_worklogs("55")
    assert len(rows) == 1
    assert rows[0].id == "te-1"
    assert rows[0].time_spent_seconds == 5400
    assert rows[0].time_spent_display == "1h 30m"
    assert rows[0].author == "Ana Lima"
    assert rows[0].author_id == "acct-1"
    assert rows[0].comment == "tracked"


@respx.mock
def test_log_work_creates_time_entry_with_date_and_time():
    route = respx.post(BASE).mock(side_effect=_graphql_response)
    row = make_provider().log_work(
        "55",
        3600,
        "2026-06-14T08:45:00.000+0000",
        "tracked",
    )
    body = json.loads(route.calls.last.request.content)
    assert "CreateTimeEntry" in body["query"]
    assert body["variables"]["accountId"] == "acct-1"
    assert body["variables"]["activityId"] == "55"
    assert body["variables"]["dateAt"] == "2026-06-14"
    assert body["variables"]["startTime"] == "08:45"
    assert body["variables"]["duration"] == 3600
    assert row.id == "te-2"
    assert row.time_spent_display == "1h"