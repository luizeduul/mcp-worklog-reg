"""MCP server for work management (Jira Cloud today, pluggable by provider).

Read/append only by design (least privilege): it can search and read issues,
read and log worklogs, and add comments. It CANNOT create, edit, transition,
assign, or delete issues, comments, or worklogs.

Tools (all prefixed ``jira_`` for the current Jira provider):
- jira_whoami, jira_search_issues, jira_get_issue, jira_add_comment,
  jira_log_work, jira_log_work_batch, jira_get_worklogs.

Config is loaded by :mod:`src.config` from a project ``.env`` (optional) or the
MCP client environment: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN. Optional:
JIRA_DAILY_JQL, WORK_PROVIDER.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

import src.config  # noqa: F401  -- imported for its .env-loading side effect
from src.tools import register_all

mcp = FastMCP("JiraWorklogMCP", log_level="ERROR")
register_all(mcp)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
