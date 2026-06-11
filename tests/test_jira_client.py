import base64
import json

import httpx
import pytest
import respx

from jira_client import JiraClient, JiraError

BASE = "https://example.atlassian.net"


def make_client() -> JiraClient:
    return JiraClient(base_url=BASE, email="me@example.com", api_token="tok")


def test_init_requires_config():
    with pytest.raises(JiraError):
        JiraClient(base_url="", email="", api_token="")


def test_auth_header_basic():
    client = make_client()
    expected = base64.b64encode(b"me@example.com:tok").decode()
    assert client._headers["Authorization"] == f"Basic {expected}"


@respx.mock
def test_current_user_via_myself():
    respx.get(f"{BASE}/rest/api/3/myself").mock(
        return_value=httpx.Response(200, json={"accountId": "abc", "displayName": "Luiz"})
    )
    client = make_client()
    current_user = client.current_user()
    assert current_user["accountId"] == "abc"
    assert current_user["displayName"] == "Luiz"


@respx.mock
def test_current_user_fallback_user_search():
    respx.get(f"{BASE}/rest/api/3/myself").mock(return_value=httpx.Response(401, json={}))
    respx.get(f"{BASE}/rest/api/3/user/search").mock(
        return_value=httpx.Response(
            200,
            json=[{"accountId": "abc", "displayName": "Luiz", "emailAddress": "me@example.com"}],
        )
    )
    client = make_client()
    current_user = client.current_user()
    assert current_user["accountId"] == "abc"


@respx.mock
def test_current_user_none_when_identity_unavailable():
    respx.get(f"{BASE}/rest/api/3/myself").mock(return_value=httpx.Response(401, json={}))
    respx.get(f"{BASE}/rest/api/3/user/search").mock(return_value=httpx.Response(200, json=[]))
    client = make_client()
    assert client.current_user() is None


@respx.mock
def test_log_work_sends_seconds_and_started():
    route = respx.post(f"{BASE}/rest/api/3/issue/PROJ-355/worklog").mock(
        return_value=httpx.Response(201, json={"id": "10001"})
    )
    client = make_client()
    adf = {"type": "doc", "version": 1, "content": []}
    response = client.log_work("PROJ-355", 9600, "2026-06-10T08:45:00.000-0300", adf)
    assert response["id"] == "10001"
    sent_request = route.calls.last.request
    body = json.loads(sent_request.content)
    assert body["timeSpentSeconds"] == 9600
    assert body["started"] == "2026-06-10T08:45:00.000-0300"
    assert body["comment"] == adf


@respx.mock
def test_log_work_without_comment_does_not_send_field():
    route = respx.post(f"{BASE}/rest/api/3/issue/PROJ-347/worklog").mock(
        return_value=httpx.Response(201, json={"id": "10002"})
    )
    client = make_client()
    client.log_work("PROJ-347", 2100, "2026-06-10T11:25:00.000-0300", None)
    body = json.loads(route.calls.last.request.content)
    assert "comment" not in body


@respx.mock
def test_get_worklogs():
    respx.get(f"{BASE}/rest/api/3/issue/PROJ-355/worklog").mock(
        return_value=httpx.Response(200, json={"worklogs": [{"id": "1", "timeSpent": "2h 40m"}]})
    )
    client = make_client()
    data = client.get_worklogs("PROJ-355")
    assert data["worklogs"][0]["id"] == "1"


@respx.mock
def test_search_issues_sends_jql():
    route = respx.post(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(200, json={"issues": [{"key": "PROJ-753"}]})
    )
    client = make_client()
    data = client.search_issues("project = PROJ", max_results=5)
    assert data["issues"][0]["key"] == "PROJ-753"
    body = json.loads(route.calls.last.request.content)
    assert body["jql"] == "project = PROJ"
    assert body["maxResults"] == 5
    assert "summary" in body["fields"]


@respx.mock
def test_network_error_becomes_jira_error():
    respx.get(f"{BASE}/rest/api/3/myself").mock(side_effect=httpx.ConnectError("offline"))
    client = make_client()
    with pytest.raises(JiraError) as exc_info:
        client.current_user()
    assert "network" in exc_info.value.message.lower()


@respx.mock
def test_unexpected_empty_response_becomes_error():
    respx.get(f"{BASE}/rest/api/3/myself").mock(return_value=httpx.Response(200, content=b""))
    client = make_client()
    with pytest.raises(JiraError) as exc_info:
        client.current_user()
    assert "empty" in exc_info.value.message.lower()


@respx.mock
def test_delete_worklog():
    respx.delete(f"{BASE}/rest/api/3/issue/PROJ-355/worklog/10001").mock(
        return_value=httpx.Response(204)
    )
    client = make_client()
    response = client.delete_worklog("PROJ-355", "10001")
    assert response == {"deleted": "10001"}


@respx.mock
def test_delete_worklog_without_permission_403():
    respx.delete(f"{BASE}/rest/api/3/issue/PROJ-355/worklog/10001").mock(
        return_value=httpx.Response(403, json={"errorMessages": ["forbidden"]})
    )
    client = make_client()
    with pytest.raises(JiraError) as exc_info:
        client.delete_worklog("PROJ-355", "10001")
    assert exc_info.value.status == 403
