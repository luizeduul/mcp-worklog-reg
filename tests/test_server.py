import json as _json
import re

import httpx
import pytest
import respx

from src.providers.jira_provider import build_adf_comment
from src.services.provider_registry import registry
from src.tools.add_comment import add_comment as jira_add_comment
from src.tools.get_task import get_task as jira_get_issue
from src.tools.get_worklogs import get_worklogs as jira_get_worklogs
from src.tools.log_work import log_work as jira_log_work
from src.tools.log_work_batch import log_work_batch as jira_log_work_batch
from src.tools.search_tasks import search_tasks as jira_search_issues
from src.tools.whoami import whoami as jira_whoami
from src.utils import parse_time_spent, to_jira_datetime

BASE = "https://example.atlassian.net"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("JIRA_BASE_URL", BASE)
    monkeypatch.setenv("JIRA_EMAIL", "me@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")
    # Isolate tests from any JIRA_DAILY_JQL loaded from a real .env at import.
    monkeypatch.delenv("JIRA_DAILY_JQL", raising=False)
    # Drop any cached provider so each test builds one against its own env/mocks.
    registry.reset()


_DAILY_JQL = 'project = BUCKET AND summary ~ "Timesheet {month} de {year}" ORDER BY created DESC'


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
    route = respx.post(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(200, json={"issues": []})
    )
    output = jira_search_issues()
    assert output["count"] == 0
    body = _json.loads(route.calls.last.request.content)
    assert "currentUser()" in body["jql"]


@respx.mock
def test_search_free_text_becomes_text_jql():
    route = respx.post(f"{BASE}/rest/api/3/search/jql").mock(
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
    body = _json.loads(route.calls.last.request.content)
    assert 'text ~ "cockpit"' in body["jql"]
    assert output["issues"][0]["key"] == "PROJ-753"
    assert output["issues"][0]["summary"] == "RFM"
    assert output["issues"][0]["status"] == "In progress"


@respx.mock
def test_get_issue_returns_compact_view():
    respx.get(f"{BASE}/rest/api/3/issue/PROJ-355").mock(
        return_value=httpx.Response(
            200,
            json={
                "key": "PROJ-355",
                "fields": {
                    "summary": "RFM cockpit",
                    "status": {"name": "In progress"},
                    "issuetype": {"name": "Task"},
                    "assignee": {"displayName": "Test User"},
                    "priority": {"name": "High"},
                    "labels": ["data"],
                    "updated": "2026-06-10T08:45:00.000-0300",
                    "description": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "Fix RFM"}]}
                        ],
                    },
                },
            },
        )
    )
    output = jira_get_issue(issue_key="PROJ-355")
    assert output["key"] == "PROJ-355"
    assert output["summary"] == "RFM cockpit"
    assert output["status"] == "In progress"
    assert output["type"] == "Task"
    assert output["assignee"] == "Test User"
    assert output["priority"] == "High"
    assert output["labels"] == ["data"]
    assert output["description"] == "Fix RFM"


@respx.mock
def test_add_comment_posts_adf():
    route = respx.post(f"{BASE}/rest/api/3/issue/PROJ-355/comment").mock(
        return_value=httpx.Response(201, json={"id": "777", "created": "2026-06-10T08:45:00.000-0300"})
    )
    output = jira_add_comment(issue_key="PROJ-355", comment="looks good")
    assert output["id"] == "777"
    assert output["issue_key"] == "PROJ-355"
    body = _json.loads(route.calls.last.request.content)
    assert body["body"]["content"][0]["content"][0]["text"] == "looks good"


def test_add_comment_rejects_empty():
    output = jira_add_comment(issue_key="PROJ-355", comment="   ")
    assert "error" in output


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
        ],
        skip_duplicates=False,
    )
    assert output["total"] == 2
    assert output["logged"] == 1
    assert output["failed"] == 1
    ok_result = next(result for result in output["results"] if result["issue_key"] == "PROJ-355")
    failed_result = next(result for result in output["results"] if result["issue_key"] == "PROJ-347")
    assert ok_result["ok"] is True and ok_result["id"] == "1"
    assert failed_result["ok"] is False and "error" in failed_result


@respx.mock
def test_log_work_batch_skips_same_time_duplicates():
    duplicate_started = to_jira_datetime("2026-06-10 08:45")
    respx.get(f"{BASE}/rest/api/3/issue/PROJ-355/worklog").mock(
        return_value=httpx.Response(
            200,
            json={"worklogs": [{"id": "99", "started": duplicate_started}]},
        )
    )
    post_route = respx.post(f"{BASE}/rest/api/3/issue/PROJ-355/worklog").mock(
        return_value=httpx.Response(201, json={"id": "1"})
    )
    output = jira_log_work_batch(
        entries=[
            {"issue_key": "PROJ-355", "time_spent": "1:00", "started": "2026-06-10 08:45"},
            {"issue_key": "PROJ-355", "time_spent": "1:00", "started": "2026-06-10 10:00"},
        ]
    )
    assert output["total"] == 2
    assert output["logged"] == 1
    assert output["skipped"] == 1
    assert output["skipped_duplicates"][0]["existing_worklog_id"] == "99"
    assert "note" in output
    # Only the non-duplicate entry was actually posted.
    assert post_route.call_count == 1


@respx.mock
def test_log_work_daily_resolves_to_month_bucket(monkeypatch):
    monkeypatch.setenv("JIRA_DAILY_JQL", _DAILY_JQL)
    search = respx.post(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(
            200,
            json={"issues": [{"key": "BUCKET-1", "fields": {"summary": "Timesheet Junho de 2026"}}]},
        )
    )
    worklog = respx.post(f"{BASE}/rest/api/3/issue/BUCKET-1/worklog").mock(
        return_value=httpx.Response(201, json={"id": "555"})
    )
    output = jira_log_work(issue_key="daily", time_spent="0:25", started="2026-06-11 09:00")
    assert output["issue_key"] == "BUCKET-1"
    assert output["resolved_from"] == "daily"
    assert output["id"] == "555"
    search_body = _json.loads(search.calls.last.request.content)
    assert "Timesheet Junho de 2026" in search_body["jql"]
    assert worklog.called


@respx.mock
def test_log_work_dayli_typo_also_resolves(monkeypatch):
    monkeypatch.setenv("JIRA_DAILY_JQL", _DAILY_JQL)
    respx.post(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(200, json={"issues": [{"key": "BUCKET-1", "fields": {}}]})
    )
    worklog = respx.post(f"{BASE}/rest/api/3/issue/BUCKET-1/worklog").mock(
        return_value=httpx.Response(201, json={"id": "9"})
    )
    output = jira_log_work(issue_key="dayli", time_spent="0:25", started="2026-06-11 09:00")
    assert output["issue_key"] == "BUCKET-1"
    assert worklog.called


@respx.mock
def test_log_work_daily_not_configured_errors():
    route = respx.post(f"{BASE}/rest/api/3/search/jql")
    output = jira_log_work(issue_key="daily", time_spent="0:25", started="2026-06-11 09:00")
    assert "error" in output
    assert "JIRA_DAILY_JQL" in output["error"]
    assert not route.called


@respx.mock
def test_log_work_daily_no_bucket_found_errors(monkeypatch):
    monkeypatch.setenv("JIRA_DAILY_JQL", _DAILY_JQL)
    respx.post(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(200, json={"issues": []})
    )
    worklog = respx.post(f"{BASE}/rest/api/3/issue/BUCKET-1/worklog")
    output = jira_log_work(issue_key="daily", time_spent="0:25", started="2026-06-11 09:00")
    assert "error" in output
    assert not worklog.called


@respx.mock
def test_log_work_batch_daily_resolves_once_and_caches(monkeypatch):
    monkeypatch.setenv("JIRA_DAILY_JQL", _DAILY_JQL)
    search = respx.post(f"{BASE}/rest/api/3/search/jql").mock(
        return_value=httpx.Response(200, json={"issues": [{"key": "BUCKET-1", "fields": {}}]})
    )
    worklog = respx.post(f"{BASE}/rest/api/3/issue/BUCKET-1/worklog").mock(
        return_value=httpx.Response(201, json={"id": "1"})
    )
    output = jira_log_work_batch(
        entries=[
            {"issue_key": "daily", "time_spent": "0:25", "started": "2026-06-11 09:00"},
            {"issue_key": "daily", "time_spent": "0:25", "started": "2026-06-12 09:00"},
        ],
        skip_duplicates=False,
    )
    assert output["logged"] == 2
    assert all(row["issue_key"] == "BUCKET-1" for row in output["results"])
    assert all(row.get("resolved_from") == "daily" for row in output["results"])
    # Same month -> one search, cached and reused.
    assert search.call_count == 1
    assert worklog.call_count == 2


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
