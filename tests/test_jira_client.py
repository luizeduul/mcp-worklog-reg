import base64
import json

import httpx
import pytest
import respx

from jira_client import JiraClient, JiraError

BASE = "https://example.atlassian.net"


def make_client() -> JiraClient:
    return JiraClient(base_url=BASE, email="me@example.com", api_token="tok")


def test_init_exige_config():
    with pytest.raises(JiraError):
        JiraClient(base_url="", email="", api_token="")


def test_auth_header_basic():
    c = make_client()
    esperado = base64.b64encode(b"me@example.com:tok").decode()
    assert c._headers["Authorization"] == f"Basic {esperado}"


@respx.mock
def test_current_user_via_myself():
    # token clássico: /myself responde direto
    respx.get(f"{BASE}/rest/api/3/myself").mock(
        return_value=httpx.Response(200, json={"accountId": "abc", "displayName": "Luiz"})
    )
    c = make_client()
    me = c.current_user()
    assert me["accountId"] == "abc"
    assert me["displayName"] == "Luiz"


@respx.mock
def test_current_user_fallback_user_search():
    # token com scopes: /myself 401 -> cai pro user/search pelo email
    respx.get(f"{BASE}/rest/api/3/myself").mock(return_value=httpx.Response(401, json={}))
    respx.get(f"{BASE}/rest/api/3/user/search").mock(
        return_value=httpx.Response(
            200,
            json=[{"accountId": "abc", "displayName": "Luiz", "emailAddress": "me@example.com"}],
        )
    )
    c = make_client()
    me = c.current_user()
    assert me["accountId"] == "abc"


@respx.mock
def test_current_user_none_quando_identidade_indisponivel():
    # /myself 401 e user/search vazio (email escondido) -> None, sem erro
    respx.get(f"{BASE}/rest/api/3/myself").mock(return_value=httpx.Response(401, json={}))
    respx.get(f"{BASE}/rest/api/3/user/search").mock(return_value=httpx.Response(200, json=[]))
    c = make_client()
    assert c.current_user() is None


@respx.mock
def test_log_work_envia_segundos_e_started():
    route = respx.post(f"{BASE}/rest/api/3/issue/ROTA-355/worklog").mock(
        return_value=httpx.Response(201, json={"id": "10001"})
    )
    c = make_client()
    adf = {"type": "doc", "version": 1, "content": []}
    res = c.log_work("ROTA-355", 9600, "2026-06-10T08:45:00.000-0300", adf)
    assert res["id"] == "10001"
    enviado = route.calls.last.request
    body = json.loads(enviado.content)
    assert body["timeSpentSeconds"] == 9600
    assert body["started"] == "2026-06-10T08:45:00.000-0300"
    assert body["comment"] == adf


@respx.mock
def test_log_work_sem_comment_nao_envia_campo():
    route = respx.post(f"{BASE}/rest/api/3/issue/ROTA-347/worklog").mock(
        return_value=httpx.Response(201, json={"id": "10002"})
    )
    c = make_client()
    c.log_work("ROTA-347", 2100, "2026-06-10T11:25:00.000-0300", None)
    body = json.loads(route.calls.last.request.content)
    assert "comment" not in body


@respx.mock
def test_get_worklogs():
    respx.get(f"{BASE}/rest/api/3/issue/ROTA-355/worklog").mock(
        return_value=httpx.Response(200, json={"worklogs": [{"id": "1", "timeSpent": "2h 40m"}]})
    )
    c = make_client()
    data = c.get_worklogs("ROTA-355")
    assert data["worklogs"][0]["id"] == "1"


@respx.mock
def test_search_issues_envia_jql():
    route = respx.post(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(200, json={"issues": [{"key": "GAZIN-753"}]})
    )
    c = make_client()
    data = c.search_issues("project = GREDOM", max_results=5)
    assert data["issues"][0]["key"] == "GAZIN-753"
    body = json.loads(route.calls.last.request.content)
    assert body["jql"] == "project = GREDOM"
    assert body["maxResults"] == 5
    assert "summary" in body["fields"]


@respx.mock
def test_erro_de_rede_vira_jira_error():
    respx.get(f"{BASE}/rest/api/3/myself").mock(side_effect=httpx.ConnectError("offline"))
    c = make_client()
    with pytest.raises(JiraError) as ei:
        c.current_user()
    assert "rede" in ei.value.message.lower()


@respx.mock
def test_resposta_vazia_inesperada_vira_erro():
    respx.get(f"{BASE}/rest/api/3/myself").mock(return_value=httpx.Response(200, content=b""))
    c = make_client()
    with pytest.raises(JiraError) as ei:
        c.current_user()
    assert "vazia" in ei.value.message.lower()


@respx.mock
def test_delete_worklog():
    respx.delete(f"{BASE}/rest/api/3/issue/ROTA-355/worklog/10001").mock(
        return_value=httpx.Response(204)
    )
    c = make_client()
    res = c.delete_worklog("ROTA-355", "10001")
    assert res == {"deleted": "10001"}


@respx.mock
def test_delete_worklog_sem_scope_403():
    respx.delete(f"{BASE}/rest/api/3/issue/ROTA-355/worklog/10001").mock(
        return_value=httpx.Response(403, json={"errorMessages": ["forbidden"]})
    )
    c = make_client()
    with pytest.raises(JiraError) as ei:
        c.delete_worklog("ROTA-355", "10001")
    assert ei.value.status == 403
