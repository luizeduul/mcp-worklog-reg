import json

import httpx
import pytest
import respx

from src.github_client import GitHubClient, GitHubError
from src.providers.github_provider import GitHubProvider

BASE = "https://api.github.com"


def make_provider(default_repo: str = "") -> GitHubProvider:
    return GitHubProvider(GitHubClient(token="t", base_url=BASE), default_repo)


@respx.mock
def test_whoami_builds_identity():
    respx.get(f"{BASE}/user").mock(
        return_value=httpx.Response(
            200,
            json={"id": 1, "login": "octocat", "name": "Octo Cat", "email": "o@x.com"},
        )
    )
    out = make_provider().whoami()
    assert out["provider"] == "github"
    assert out["ok"] is True
    assert out["accountId"] == "1"
    assert out["displayName"] == "Octo Cat"
    assert out["emailAddress"] == "o@x.com"


@respx.mock
def test_search_default_uses_assigned_to_me():
    route = respx.get(f"{BASE}/search/issues").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "number": 7,
                        "title": "Fix bug",
                        "state": "open",
                        "html_url": "https://github.com/octo/repo/issues/7",
                        "repository_url": f"{BASE}/repos/octo/repo",
                    }
                ]
            },
        )
    )
    tasks = make_provider().search_tasks()
    assert "assignee:@me" in route.calls.last.request.url.params["q"]
    assert tasks[0].id == "octo/repo#7"
    assert tasks[0].summary == "Fix bug"
    assert tasks[0].status == "open"
    assert tasks[0].url == "https://github.com/octo/repo/issues/7"


@respx.mock
def test_search_scopes_to_default_repo():
    route = respx.get(f"{BASE}/search/issues").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    make_provider(default_repo="octo/repo").search_tasks(query="login")
    assert "repo:octo/repo" in route.calls.last.request.url.params["q"]
    assert "login" in route.calls.last.request.url.params["q"]


@respx.mock
def test_search_native_query_passthrough():
    route = respx.get(f"{BASE}/search/issues").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    make_provider(default_repo="octo/repo").search_tasks(
        native_query="repo:other/x is:issue label:bug"
    )
    # Raw query is sent verbatim; default repo scope is NOT appended.
    assert route.calls.last.request.url.params["q"] == "repo:other/x is:issue label:bug"


@respx.mock
def test_get_task_maps_fields_and_url():
    respx.get(f"{BASE}/repos/octo/repo/issues/7").mock(
        return_value=httpx.Response(
            200,
            json={
                "number": 7,
                "title": "Fix bug",
                "state": "open",
                "assignee": {"login": "octocat"},
                "labels": [{"name": "bug"}, {"name": "p1"}],
                "body": "details",
                "updated_at": "2026-06-10T12:00:00Z",
                "html_url": "https://github.com/octo/repo/issues/7",
            },
        )
    )
    task = make_provider().get_task("octo/repo#7")
    assert task.id == "octo/repo#7"
    assert task.task_type == "issue"
    assert task.assignee == "octocat"
    assert task.labels == ["bug", "p1"]
    assert task.url == "https://github.com/octo/repo/issues/7"


@respx.mock
def test_get_task_accepts_bare_number_with_default_repo():
    route = respx.get(f"{BASE}/repos/octo/repo/issues/7").mock(
        return_value=httpx.Response(200, json={"number": 7, "title": "x", "state": "open"})
    )
    make_provider(default_repo="octo/repo").get_task("7")
    assert route.called


def test_invalid_ref_raises():
    with pytest.raises(GitHubError):
        make_provider().get_task("7")  # bare number, no default repo


@respx.mock
def test_add_comment_posts_body():
    route = respx.post(f"{BASE}/repos/octo/repo/issues/7/comments").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 555,
                "user": {"login": "octocat"},
                "created_at": "2026-06-10T12:00:00Z",
            },
        )
    )
    comment = make_provider().add_comment("octo/repo#7", "looks good")
    assert json.loads(route.calls.last.request.content) == {"body": "looks good"}
    assert comment.id == "555"
    assert comment.author == "octocat"
    assert comment.body == "looks good"


def test_worklogs_unsupported():
    provider = make_provider()
    assert provider.capabilities.supports_worklogs is False
    with pytest.raises(NotImplementedError):
        provider.log_work("octo/repo#7", 3600, "2026-06-10T08:00:00.000-0300")
    with pytest.raises(NotImplementedError):
        provider.get_worklogs("octo/repo#7")
