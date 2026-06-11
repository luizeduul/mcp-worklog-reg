import json as _json
import re

import httpx
import pytest
import respx

from server import (
    build_adf_comment,
    build_daily_jql,
    jira_delete_worklog,
    jira_get_worklogs,
    jira_log_work,
    jira_log_work_batch,
    jira_resolve_daily_issue,
    jira_search_issues,
    jira_whoami,
    parse_time_spent,
    render_daily_search_text,
    to_jira_datetime,
)

BASE = "https://example.atlassian.net"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("JIRA_BASE_URL", BASE)
    monkeypatch.setenv("JIRA_EMAIL", "me@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")


def test_parse_time_spent_hhmm():
    assert parse_time_spent("2:40") == 9600
    assert parse_time_spent("0:20") == 1200
    assert parse_time_spent("0:35") == 2100


def test_parse_time_spent_jira_style():
    assert parse_time_spent("1h 30m") == 5400
    assert parse_time_spent("45m") == 2700
    assert parse_time_spent("2h") == 7200


def test_parse_time_spent_invalid():
    with pytest.raises(ValueError):
        parse_time_spent("abc")
    with pytest.raises(ValueError):
        parse_time_spent("0:00")
    with pytest.raises(ValueError):
        parse_time_spent("2:4")


def test_to_jira_datetime_date_and_time():
    output = to_jira_datetime("2026-06-10 08:45")
    assert output.startswith("2026-06-10T08:45:00.")
    assert re.match(r"^2026-06-10T08:45:00\.\d{3}[+-]\d{4}$", output)


def test_to_jira_datetime_date_only_becomes_midnight():
    output = to_jira_datetime("2026-06-10")
    assert output.startswith("2026-06-10T00:00:00.")


def test_to_jira_datetime_invalid():
    with pytest.raises(ValueError):
        to_jira_datetime("10/06/2026")


def test_build_adf_comment():
    adf = build_adf_comment("adjust RFM filter")
    assert adf["type"] == "doc"
    assert adf["version"] == 1
    assert adf["content"][0]["content"][0]["text"] == "adjust RFM filter"


def test_render_daily_search_text_template(monkeypatch):
    monkeypatch.setenv("JIRA_DAILY_SEARCH_TEXT", "Daily {month_name_pt} {year}")
    assert render_daily_search_text("2026-06-10") == "Daily junho 2026"


def test_build_daily_jql_with_project(monkeypatch):
    monkeypatch.setenv("JIRA_DAILY_SEARCH_TEXT", 'Daily "{month_name_en}" {year}')
    monkeypatch.setenv("JIRA_DAILY_PROJECT", "PROJ")
    jql, search_text = build_daily_jql("2026-06-10")
    assert search_text == 'Daily "june" 2026'
    assert jql == 'project = "PROJ" AND text ~ "Daily \\"june\\" 2026" ORDER BY updated DESC'


@respx.mock
def test_jira_whoami_with_identity():
    respx.get(f"{BASE}/rest/api/3/myself").mock(
        return_value=httpx.Response(200, json={"accountId": "abc", "displayName": "Test User"})
    )
    output = jira_whoami()
    assert output["ok"] is True
    assert output["accountId"] == "abc"
    assert output["displayName"] == "Test User"


@respx.mock
def test_jira_whoami_scoped_without_identity():
    respx.get(f"{BASE}/rest/api/3/myself").mock(return_value=httpx.Response(401, json={}))
    respx.get(f"{BASE}/rest/api/3/user/search").mock(return_value=httpx.Response(200, json=[]))
    respx.post(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(200, json={"issues": []})
    )
    output = jira_whoami()
    assert output["ok"] is True
    assert "note" in output


@respx.mock
def test_jira_whoami_real_error():
    respx.get(f"{BASE}/rest/api/3/myself").mock(return_value=httpx.Response(401, json={}))
    respx.get(f"{BASE}/rest/api/3/user/search").mock(return_value=httpx.Response(401, json={}))
    output = jira_whoami()
    assert "error" in output
    assert "token" in output["error"].lower()


@respx.mock
def test_search_default_current_user_open_issues():
    respx.post(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(200, json={"issues": []})
    )
    output = jira_search_issues()
    assert "currentUser()" in output["jql"]
    assert output["count"] == 0


@respx.mock
def test_search_free_text_becomes_text_jql():
    respx.post(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(
            200,
            json={
                "issues": [
                    {
                        "key": "PROJ-753",
                        "fields": {
                            "summary": "RFM",
                            "status": {"name": "In progress"},
                        },
                    }
                ]
            },
        )
    )
    output = jira_search_issues(query="cockpit")
    assert 'text ~ "cockpit"' in output["jql"]
    assert output["issues"][0]["key"] == "PROJ-753"
    assert output["issues"][0]["summary"] == "RFM"
    assert output["issues"][0]["status"] == "In progress"


@respx.mock
def test_resolve_daily_issue_uses_env(monkeypatch):
    monkeypatch.setenv("JIRA_DAILY_SEARCH_TEXT", "Daily {month_name_en} {year}")
    monkeypatch.setenv("JIRA_DAILY_PROJECT", "PROJ")
    route = respx.post(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(
            200,
            json={
                "issues": [
                    {
                        "key": "PROJ-123",
                        "fields": {
                            "summary": "Daily june 2026",
                            "status": {"name": "Open"},
                        },
                    }
                ]
            },
        )
    )
    output = jira_resolve_daily_issue(reference_date="2026-06-10")
    body = _json.loads(route.calls.last.request.content)
    assert output["search_text"] == "Daily june 2026"
    assert output["issues"][0]["key"] == "PROJ-123"
    assert body["jql"] == 'project = "PROJ" AND text ~ "Daily june 2026" ORDER BY updated DESC'


@respx.mock
def test_log_work_converts_and_sends_payload():
    route = respx.post(f"{BASE}/rest/api/3/issue/PROJ-355/worklog").mock(
        return_value=httpx.Response(201, json={"id": "10001"})
    )
    output = jira_log_work(
        issue_key="PROJ-355",
        time_spent="2:40",
        started="2026-06-10 08:45",
        comment="tracking investigation",
    )
    assert output["id"] == "10001"
    assert output["time_spent_seconds"] == 9600
    body = _json.loads(route.calls.last.request.content)
    assert body["timeSpentSeconds"] == 9600
    assert body["started"].startswith("2026-06-10T08:45:00.")
    assert body["comment"]["content"][0]["content"][0]["text"] == "tracking investigation"


@respx.mock
def test_log_work_invalid_time_does_not_call_api():
    route = respx.post(f"{BASE}/rest/api/3/issue/PROJ-355/worklog")
    output = jira_log_work(issue_key="PROJ-355", time_spent="xx", started="2026-06-10 08:45")
    assert "error" in output
    assert not route.called


@respx.mock
def test_log_work_batch_mixes_success_and_failure():
    respx.post(f"{BASE}/rest/api/3/issue/PROJ-355/worklog").mock(
        return_value=httpx.Response(201, json={"id": "1"})
    )
    respx.post(f"{BASE}/rest/api/3/issue/PROJ-347/worklog").mock(
        return_value=httpx.Response(404, json={"errorMessages": ["does not exist"]})
    )
    output = jira_log_work_batch(
        entries=[
            {
                "issue_key": "PROJ-355",
                "time_spent": "2:40",
                "started": "2026-06-10 08:45",
                "comment": "ok",
            },
            {"issue_key": "PROJ-347", "time_spent": "0:35", "started": "2026-06-10 11:25"},
        ]
    )
    assert output["total"] == 2
    assert output["ok"] == 1
    assert output["failed"] == 1
    ok_result = next(result for result in output["results"] if result["issue_key"] == "PROJ-355")
    failed_result = next(result for result in output["results"] if result["issue_key"] == "PROJ-347")
    assert ok_result["ok"] is True and ok_result["id"] == "1"
    assert failed_result["ok"] is False and "error" in failed_result


@respx.mock
def test_get_worklogs_mine_only_filters():
    respx.get(f"{BASE}/rest/api/3/myself").mock(
        return_value=httpx.Response(200, json={"accountId": "me"})
    )
    respx.get(f"{BASE}/rest/api/3/issue/PROJ-355/worklog").mock(
        return_value=httpx.Response(
            200,
            json={
                "worklogs": [
                    {
                        "id": "1",
                        "author": {"accountId": "me", "displayName": "Test User"},
                        "timeSpent": "2h 40m",
                        "started": "x",
                    },
                    {
                        "id": "2",
                        "author": {"accountId": "other", "displayName": "Other User"},
                        "timeSpent": "1h",
                        "started": "y",
                    },
                ]
            },
        )
    )
    output = jira_get_worklogs(issue_key="PROJ-355", mine_only=True)
    assert output["count"] == 1
    assert output["worklogs"][0]["id"] == "1"


@respx.mock
def test_get_worklogs_mine_only_degrades_without_identity():
    respx.get(f"{BASE}/rest/api/3/myself").mock(return_value=httpx.Response(401, json={}))
    respx.get(f"{BASE}/rest/api/3/user/search").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{BASE}/rest/api/3/issue/PROJ-355/worklog").mock(
        return_value=httpx.Response(
            200,
            json={
                "worklogs": [
                    {
                        "id": "1",
                        "author": {"accountId": "me", "displayName": "Test User"},
                        "timeSpent": "2h 40m",
                        "started": "x",
                    },
                    {
                        "id": "2",
                        "author": {"accountId": "other", "displayName": "Other User"},
                        "timeSpent": "1h",
                        "started": "y",
                    },
                ]
            },
        )
    )
    output = jira_get_worklogs(issue_key="PROJ-355", mine_only=True)
    assert output["count"] == 2
    assert "note" in output


@respx.mock
def test_delete_worklog_tool():
    respx.delete(f"{BASE}/rest/api/3/issue/PROJ-355/worklog/10001").mock(
        return_value=httpx.Response(204)
    )
    output = jira_delete_worklog(issue_key="PROJ-355", worklog_id="10001")
    assert output["deleted"] == "10001"
