import json

import httpx
import respx

from src.providers.redmine_provider import RedmineProvider
from src.redmine_client import RedmineClient

BASE = "https://redmine.example.com"


def make_provider(activity_id=None) -> RedmineProvider:
    return RedmineProvider(RedmineClient(base_url=BASE, api_key="key"), activity_id)


@respx.mock
def test_whoami_builds_identity():
    respx.get(f"{BASE}/users/current.json").mock(
        return_value=httpx.Response(
            200,
            json={"user": {"id": 7, "firstname": "Ana", "lastname": "Lima", "mail": "a@x.com"}},
        )
    )
    out = make_provider().whoami()
    assert out["provider"] == "redmine"
    assert out["ok"] is True
    assert out["accountId"] == "7"
    assert out["displayName"] == "Ana Lima"
    assert out["emailAddress"] == "a@x.com"


@respx.mock
def test_search_default_uses_assigned_to_me():
    route = respx.get(f"{BASE}/issues.json").mock(
        return_value=httpx.Response(
            200,
            json={"issues": [{"id": 12, "subject": "Fix bug", "status": {"name": "New"}}]},
        )
    )
    tasks = make_provider().search_tasks()
    assert tasks[0].id == "12"
    assert tasks[0].summary == "Fix bug"
    assert tasks[0].status == "New"
    assert route.calls.last.request.url.params["assigned_to_id"] == "me"


@respx.mock
def test_search_free_text_uses_search_endpoint():
    respx.get(f"{BASE}/search.json").mock(
        return_value=httpx.Response(
            200,
            json={"results": [{"id": 5, "title": "Bug #5: login", "url": f"{BASE}/issues/5"}]},
        )
    )
    tasks = make_provider().search_tasks(query="login")
    assert tasks[0].id == "5"
    assert tasks[0].summary == "Bug #5: login"


@respx.mock
def test_search_native_query_parsed_into_params():
    route = respx.get(f"{BASE}/issues.json").mock(
        return_value=httpx.Response(200, json={"issues": []})
    )
    make_provider().search_tasks(native_query="project_id=3&tracker_id=2")
    params = route.calls.last.request.url.params
    assert params["project_id"] == "3"
    assert params["tracker_id"] == "2"


@respx.mock
def test_get_task_maps_fields_and_url():
    respx.get(f"{BASE}/issues/12.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "issue": {
                    "id": 12,
                    "subject": "Fix bug",
                    "status": {"name": "New"},
                    "tracker": {"name": "Bug"},
                    "assigned_to": {"name": "Ana Lima"},
                    "priority": {"name": "High"},
                    "description": "details",
                    "updated_on": "2026-06-10T12:00:00Z",
                }
            },
        )
    )
    task = make_provider().get_task("12")
    assert task.task_type == "Bug"
    assert task.assignee == "Ana Lima"
    assert task.url == f"{BASE}/issues/12"


@respx.mock
def test_log_work_converts_seconds_to_hours_and_date():
    route = respx.post(f"{BASE}/time_entries.json").mock(
        return_value=httpx.Response(201, json={"time_entry": {"id": 50}})
    )
    worklog = make_provider(activity_id=9).log_work(
        "12", 9000, "2026-06-10T08:45:00.000-0300", "dev"
    )
    body = json.loads(route.calls.last.request.content)["time_entry"]
    assert body["hours"] == 2.5
    assert body["spent_on"] == "2026-06-10"
    assert body["activity_id"] == 9
    assert worklog.id == "50"
    assert worklog.time_spent_display == "2.5h"


@respx.mock
def test_add_comment_appends_note():
    route = respx.put(f"{BASE}/issues/12.json").mock(return_value=httpx.Response(204))
    comment = make_provider().add_comment("12", "looks good")
    assert json.loads(route.calls.last.request.content) == {"issue": {"notes": "looks good"}}
    assert comment.body == "looks good"


def test_group_entries_collapses_same_task_and_day():
    entries = [
        {"task_id": "12", "seconds": 3600, "started": "2026-06-10T08:00:00.000-0300", "comment": "dev", "is_daily": False},
        {"task_id": "12", "seconds": 1800, "started": "2026-06-10T14:00:00.000-0300", "comment": "review", "is_daily": False},
        {"task_id": "12", "seconds": 3600, "started": "2026-06-11T09:00:00.000-0300", "comment": "dev", "is_daily": False},
        {"task_id": "99", "seconds": 900, "started": "2026-06-10T10:00:00.000-0300", "comment": "", "is_daily": False},
    ]
    grouped = make_provider().group_entries(entries)
    # 12@2026-06-10 (merged), 12@2026-06-11, 99@2026-06-10 -> 3 groups
    assert len(grouped) == 3
    first = grouped[0]
    assert first["task_id"] == "12"
    assert first["seconds"] == 5400
    assert first["comment"] == "dev; review"


@respx.mock
def test_get_worklogs_maps_entries():
    respx.get(f"{BASE}/time_entries.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "time_entries": [
                    {
                        "id": 3,
                        "user": {"id": 7, "name": "Ana Lima"},
                        "hours": 2.0,
                        "spent_on": "2026-06-10",
                        "comments": "dev",
                    }
                ]
            },
        )
    )
    worklogs = make_provider().get_worklogs("12")
    assert worklogs[0].time_spent_seconds == 7200
    assert worklogs[0].author_id == "7"
    assert worklogs[0].started == "2026-06-10"
