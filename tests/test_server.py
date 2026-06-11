import json as _json
import re

import httpx
import pytest
import respx

from server import (
    build_adf_comment,
    jira_delete_worklog,
    jira_get_worklogs,
    jira_log_work,
    jira_log_work_batch,
    jira_search_issues,
    jira_whoami,
    parse_time_spent,
    to_jira_datetime,
)

BASE = "https://example.atlassian.net"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("JIRA_BASE_URL", BASE)
    monkeypatch.setenv("JIRA_EMAIL", "me@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")


# ---------------------------------------------------------------------------
# Task 4: helpers de conversão (puros)
# ---------------------------------------------------------------------------


def test_parse_time_spent_hhmm():
    assert parse_time_spent("2:40") == 9600
    assert parse_time_spent("0:20") == 1200
    assert parse_time_spent("0:35") == 2100


def test_parse_time_spent_estilo_jira():
    assert parse_time_spent("1h 30m") == 5400
    assert parse_time_spent("45m") == 2700
    assert parse_time_spent("2h") == 7200


def test_parse_time_spent_invalido():
    with pytest.raises(ValueError):
        parse_time_spent("abc")
    with pytest.raises(ValueError):
        parse_time_spent("0:00")
    # minuto de 1 dígito é ambíguo (typo de H:MM) → rejeita, não vira valor errado
    with pytest.raises(ValueError):
        parse_time_spent("2:4")


def test_to_jira_datetime_data_e_hora():
    out = to_jira_datetime("2026-06-10 08:45")
    # prefixo fixo; offset depende do fuso local da máquina
    assert out.startswith("2026-06-10T08:45:00.")
    assert re.match(r"^2026-06-10T08:45:00\.\d{3}[+-]\d{4}$", out)


def test_to_jira_datetime_so_data_vira_meia_noite():
    out = to_jira_datetime("2026-06-10")
    assert out.startswith("2026-06-10T00:00:00.")


def test_to_jira_datetime_invalido():
    with pytest.raises(ValueError):
        to_jira_datetime("10/06/2026")


def test_build_adf_comment():
    adf = build_adf_comment("ajuste filtro RFM")
    assert adf["type"] == "doc"
    assert adf["version"] == 1
    assert adf["content"][0]["content"][0]["text"] == "ajuste filtro RFM"


# ---------------------------------------------------------------------------
# Task 5: tools jira_whoami e jira_search_issues
# ---------------------------------------------------------------------------


@respx.mock
def test_jira_whoami_com_identidade():
    # token clássico: /myself responde -> identidade direta
    respx.get(f"{BASE}/rest/api/3/myself").mock(
        return_value=httpx.Response(200, json={"accountId": "abc", "displayName": "Luiz"})
    )
    out = jira_whoami()
    assert out["ok"] is True
    assert out["accountId"] == "abc"
    assert out["displayName"] == "Luiz"


@respx.mock
def test_jira_whoami_scoped_sem_identidade():
    # token com scopes: /myself 401, user/search vazio -> confirma auth via busca + nota
    respx.get(f"{BASE}/rest/api/3/myself").mock(return_value=httpx.Response(401, json={}))
    respx.get(f"{BASE}/rest/api/3/user/search").mock(return_value=httpx.Response(200, json=[]))
    respx.post(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(200, json={"issues": []})
    )
    out = jira_whoami()
    assert out["ok"] is True
    assert "nota" in out


@respx.mock
def test_jira_whoami_erro_real():
    # token inválido de verdade: /myself 401 e user/search também 401 -> erro
    respx.get(f"{BASE}/rest/api/3/myself").mock(return_value=httpx.Response(401, json={}))
    respx.get(f"{BASE}/rest/api/3/user/search").mock(return_value=httpx.Response(401, json={}))
    out = jira_whoami()
    assert "erro" in out
    assert "token" in out["erro"].lower()


@respx.mock
def test_search_default_minhas_abertas():
    route = respx.post(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(200, json={"issues": []})
    )
    out = jira_search_issues()
    assert "currentUser()" in out["jql"]
    assert out["count"] == 0


@respx.mock
def test_search_query_livre_vira_text():
    respx.post(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(
            200,
            json={"issues": [{"key": "GAZIN-753", "fields": {"summary": "RFM", "status": {"name": "Em andamento"}}}]},
        )
    )
    out = jira_search_issues(query="cockpit")
    assert 'text ~ "cockpit"' in out["jql"]
    assert out["issues"][0]["key"] == "GAZIN-753"
    assert out["issues"][0]["summary"] == "RFM"
    assert out["issues"][0]["status"] == "Em andamento"


# ---------------------------------------------------------------------------
# Task 6: tools log_work, log_work_batch, get_worklogs, delete_worklog
# ---------------------------------------------------------------------------


@respx.mock
def test_log_work_converte_e_envia():
    route = respx.post(f"{BASE}/rest/api/3/issue/ROTA-355/worklog").mock(
        return_value=httpx.Response(201, json={"id": "10001"})
    )
    out = jira_log_work(
        issue_key="ROTA-355",
        time_spent="2:40",
        started="2026-06-10 08:45",
        comment="investigacoes de rastreamento",
    )
    assert out["id"] == "10001"
    assert out["time_spent_seconds"] == 9600
    body = _json.loads(route.calls.last.request.content)
    assert body["timeSpentSeconds"] == 9600
    assert body["started"].startswith("2026-06-10T08:45:00.")
    assert body["comment"]["content"][0]["content"][0]["text"] == "investigacoes de rastreamento"


@respx.mock
def test_log_work_tempo_invalido_nao_chama_api():
    route = respx.post(f"{BASE}/rest/api/3/issue/ROTA-355/worklog")
    out = jira_log_work(issue_key="ROTA-355", time_spent="xx", started="2026-06-10 08:45")
    assert "erro" in out
    assert not route.called


@respx.mock
def test_log_work_batch_mistura_sucesso_e_falha():
    respx.post(f"{BASE}/rest/api/3/issue/ROTA-355/worklog").mock(
        return_value=httpx.Response(201, json={"id": "1"})
    )
    respx.post(f"{BASE}/rest/api/3/issue/ROTA-347/worklog").mock(
        return_value=httpx.Response(404, json={"errorMessages": ["nao existe"]})
    )
    out = jira_log_work_batch(
        entries=[
            {"issue_key": "ROTA-355", "time_spent": "2:40", "started": "2026-06-10 08:45", "comment": "ok"},
            {"issue_key": "ROTA-347", "time_spent": "0:35", "started": "2026-06-10 11:25"},
        ]
    )
    assert out["total"] == 2
    assert out["ok"] == 1
    assert out["failed"] == 1
    r_ok = next(r for r in out["results"] if r["issue_key"] == "ROTA-355")
    r_fail = next(r for r in out["results"] if r["issue_key"] == "ROTA-347")
    assert r_ok["ok"] is True and r_ok["id"] == "1"
    assert r_fail["ok"] is False and "error" in r_fail


@respx.mock
def test_get_worklogs_mine_only_filtra():
    respx.get(f"{BASE}/rest/api/3/myself").mock(
        return_value=httpx.Response(200, json={"accountId": "me"})
    )
    respx.get(f"{BASE}/rest/api/3/issue/ROTA-355/worklog").mock(
        return_value=httpx.Response(
            200,
            json={
                "worklogs": [
                    {"id": "1", "author": {"accountId": "me", "displayName": "Luiz"}, "timeSpent": "2h 40m", "started": "x"},
                    {"id": "2", "author": {"accountId": "outro", "displayName": "Fulano"}, "timeSpent": "1h", "started": "y"},
                ]
            },
        )
    )
    out = jira_get_worklogs(issue_key="ROTA-355", mine_only=True)
    assert out["count"] == 1
    assert out["worklogs"][0]["id"] == "1"


@respx.mock
def test_get_worklogs_mine_only_degrada_sem_identidade():
    # token com scopes: identidade indisponível -> mine_only vira no-op + nota
    respx.get(f"{BASE}/rest/api/3/myself").mock(return_value=httpx.Response(401, json={}))
    respx.get(f"{BASE}/rest/api/3/user/search").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{BASE}/rest/api/3/issue/ROTA-355/worklog").mock(
        return_value=httpx.Response(
            200,
            json={
                "worklogs": [
                    {"id": "1", "author": {"accountId": "me", "displayName": "Luiz"}, "timeSpent": "2h 40m", "started": "x"},
                    {"id": "2", "author": {"accountId": "outro", "displayName": "Fulano"}, "timeSpent": "1h", "started": "y"},
                ]
            },
        )
    )
    out = jira_get_worklogs(issue_key="ROTA-355", mine_only=True)
    assert out["count"] == 2  # não filtrou
    assert "nota" in out


@respx.mock
def test_delete_worklog_tool():
    respx.delete(f"{BASE}/rest/api/3/issue/ROTA-355/worklog/10001").mock(
        return_value=httpx.Response(204)
    )
    out = jira_delete_worklog(issue_key="ROTA-355", worklog_id="10001")
    assert out["deleted"] == "10001"
