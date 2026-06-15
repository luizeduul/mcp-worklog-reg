import json

import httpx
import pytest
import respx

from src.github_client import GitHubClient, GitHubError

BASE = "https://api.github.com"


def make_client() -> GitHubClient:
    return GitHubClient(token="t0ken", base_url=BASE)


def test_requires_token():
    with pytest.raises(GitHubError):
        GitHubClient(token="")


def test_rejects_non_http_scheme():
    with pytest.raises(GitHubError):
        GitHubClient(token="t", base_url="ftp://api.github.com")


def test_strips_trailing_slash():
    assert make_client().base_url == BASE
    assert GitHubClient(token="t", base_url=f"{BASE}/").base_url == BASE


@respx.mock
def test_sends_bearer_auth_header():
    route = respx.get(f"{BASE}/user").mock(
        return_value=httpx.Response(200, json={"login": "octocat", "id": 1})
    )
    make_client().current_user()
    assert route.calls.last.request.headers["Authorization"] == "Bearer t0ken"
    assert route.calls.last.request.headers["X-GitHub-Api-Version"] == "2022-11-28"


@respx.mock
def test_search_issues_sends_query_params():
    route = respx.get(f"{BASE}/search/issues").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    make_client().search_issues("assignee:@me", 15, sort="updated")
    params = route.calls.last.request.url.params
    assert params["q"] == "assignee:@me"
    assert params["per_page"] == "15"
    assert params["sort"] == "updated"
    assert params["order"] == "desc"


@respx.mock
def test_add_comment_posts_body():
    route = respx.post(f"{BASE}/repos/octo/repo/issues/7/comments").mock(
        return_value=httpx.Response(201, json={"id": 99})
    )
    make_client().add_comment("octo", "repo", "7", "looks good")
    assert json.loads(route.calls.last.request.content) == {"body": "looks good"}


@respx.mock
def test_maps_401_to_friendly_error():
    respx.get(f"{BASE}/user").mock(
        return_value=httpx.Response(401, json={"message": "Bad credentials"})
    )
    with pytest.raises(GitHubError) as exc:
        make_client().current_user()
    assert exc.value.status == 401


@respx.mock
def test_network_failure_wrapped():
    respx.get(f"{BASE}/user").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(GitHubError):
        make_client().current_user()
