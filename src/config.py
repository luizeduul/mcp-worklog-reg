"""Runtime configuration: loads ``.env`` and selects the active provider.

Importing this module loads the project ``.env`` (next to the repo root) if
present. The file is optional; values may also come from the MCP client env.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# .env lives at the repository root, one level above this package.
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

DEFAULT_PROVIDER = os.getenv("WORK_PROVIDER", "jira")
"""Provider used when a tool does not name one explicitly."""
