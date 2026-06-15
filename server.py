"""Repo-root launcher kept so existing MCP registrations that run ``server.py``
keep working. The implementation now lives in :mod:`src.server`.
"""

from src.server import main, mcp  # noqa: F401  (mcp re-exported for tooling)

if __name__ == "__main__":
    main()
