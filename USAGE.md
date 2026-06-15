# worklog-mcp usage

English documentation comes first, matching README style. A Portuguese section is included below.

- [English](#english)
- [Portugues](#portugues)

---

## English

Quick reference for the MCP server that logs and checks worklogs across multiple providers (Jira Cloud, Redmine, GitHub, Artia) through AI agents.

### 1. Prerequisites

- `uv` installed (Python/dependencies/runtime):
  `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- Account in one supported provider with permission to log work:
  - Jira Cloud
  - Redmine
  - GitHub
  - Artia

### 2. Environment Variables by Provider

#### 2.1 Jira Cloud

| Variable | Required | Description |
|---|---|---|
| `JIRA_BASE_URL` | yes | `https://<your-instance>.atlassian.net` (HTTPS and `*.atlassian.net`) |
| `JIRA_EMAIL` | yes | Atlassian account email |
| `JIRA_API_TOKEN` | yes | Classic API token |
| `JIRA_DAILY_JQL` | no | JQL template for `issue_key="daily"`. `{month}` and `{year}` are filled from worklog date. |

Use a classic Jira API token (not "with scopes") for best compatibility with team-managed projects.

#### 2.2 Redmine

| Variable | Required | Description |
|---|---|---|
| `REDMINE_URL` | yes | Redmine base URL, for example `https://redmine.example.com` |
| `REDMINE_API_KEY` | yes | Redmine API key from account settings |

#### 2.3 GitHub

| Variable | Required | Description |
|---|---|---|
| `GITHUB_TOKEN` | yes | Personal Access Token with `repo` and `user` scopes |
| `GITHUB_REPO` | no | Default repo (`owner/repo`) for shorthand issue references |

#### 2.4 Artia

| Variable | Required | Description |
|---|---|---|
| `ARTIA_CLIENT_ID` | yes | Client ID from Artia integrations |
| `ARTIA_SECRET` | yes | Integration secret |
| `ARTIA_ACCOUNT_ID` | yes | Account/workspace id |
| `ARTIA_FOLDER_ID` | no | Default folder for `search_tasks` |

#### 2.5 Provider Selection

| Variable | Required | Description |
|---|---|---|
| `WORK_PROVIDER` | no | Active provider: `jira`, `redmine`, `github`, `artia`. Default: `jira`. |

Variables can come from `.env` next to root `server.py` or from the MCP client environment.

### 3. Link This MCP Server to AI Agents

Keep paths generic and machine-local. Suggested shell variables:

```powershell
$env:UV_PATH = "C:/path/to/uv.exe"
$env:MCP_PROJECT_DIR = "C:/path/to/worklog-mcp"
```

Provider-ready environment blocks (PowerShell):

- They set environment variables in the current terminal session only.
- They are useful for quick tests and temporary provider switching.
- They are not the same as editing `.env`, which persists values in a file for reuse.
- If both are present, MCP client-provided env values usually take precedence.

```powershell
# Jira
$env:WORK_PROVIDER = "jira"
$env:JIRA_BASE_URL = "https://your-company.atlassian.net"
$env:JIRA_EMAIL = "you@example.com"
$env:JIRA_API_TOKEN = "your-token"

# Redmine
$env:WORK_PROVIDER = "redmine"
$env:REDMINE_URL = "https://redmine.example.com"
$env:REDMINE_API_KEY = "your-key"

# GitHub
$env:WORK_PROVIDER = "github"
$env:GITHUB_TOKEN = "your-token"
$env:GITHUB_REPO = "owner/repo"

# Artia
$env:WORK_PROVIDER = "artia"
$env:ARTIA_CLIENT_ID = "your-client-id"
$env:ARTIA_SECRET = "your-secret"
$env:ARTIA_ACCOUNT_ID = "your-account-id"
$env:ARTIA_FOLDER_ID = "optional-folder-id"
```

#### 3.1 Claude Code (CLI)

```powershell
claude mcp add worklog-mcp --scope user `
  -e WORK_PROVIDER=jira `
  -e JIRA_BASE_URL=https://your-company.atlassian.net `
  -e JIRA_EMAIL=you@example.com `
  -e JIRA_API_TOKEN=your-token `
  -- $env:UV_PATH --directory $env:MCP_PROJECT_DIR run server.py
```

#### 3.2 Claude Desktop

Edit `%APPDATA%/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "worklog-mcp": {
      "command": "powershell",
      "args": [
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "& $env:UV_PATH --directory $env:MCP_PROJECT_DIR run server.py"
      ],
      "env": {
        "WORK_PROVIDER": "jira",
        "JIRA_BASE_URL": "https://your-company.atlassian.net",
        "JIRA_EMAIL": "you@example.com",
        "JIRA_API_TOKEN": "your-token"
      }
    }
  }
}
```

#### 3.3 Codex-compatible clients

For Codex clients that support MCP via config file, use a stdio server entry with `command`, `args`, and `env`. Example template:

```json
{
  "mcpServers": {
    "worklog-mcp": {
      "command": "C:/path/to/uv.exe",
      "args": ["--directory", "C:/path/to/worklog-mcp", "run", "server.py"],
      "env": {
        "WORK_PROVIDER": "jira",
        "JIRA_BASE_URL": "https://your-company.atlassian.net",
        "JIRA_EMAIL": "you@example.com",
        "JIRA_API_TOKEN": "your-token"
      }
    }
  }
}
```

If your Codex client uses TOML instead of JSON, map the same fields (`command`, `args`, `env`) in its MCP section.

Provider-ready `env` snippets for JSON configs:

```json
{
  "WORK_PROVIDER": "jira",
  "JIRA_BASE_URL": "https://your-company.atlassian.net",
  "JIRA_EMAIL": "you@example.com",
  "JIRA_API_TOKEN": "your-token"
}
```

```json
{
  "WORK_PROVIDER": "redmine",
  "REDMINE_URL": "https://redmine.example.com",
  "REDMINE_API_KEY": "your-key"
}
```

```json
{
  "WORK_PROVIDER": "github",
  "GITHUB_TOKEN": "your-token",
  "GITHUB_REPO": "owner/repo"
}
```

```json
{
  "WORK_PROVIDER": "artia",
  "ARTIA_CLIENT_ID": "your-client-id",
  "ARTIA_SECRET": "your-secret",
  "ARTIA_ACCOUNT_ID": "your-account-id",
  "ARTIA_FOLDER_ID": "optional-folder-id"
}
```

#### 3.4 Cline (VS Code extension)

In Cline MCP settings, add a server entry using the same stdio command:

```json
{
  "mcpServers": {
    "worklog-mcp": {
      "command": "C:/path/to/uv.exe",
      "args": ["--directory", "C:/path/to/worklog-mcp", "run", "server.py"],
      "env": {
        "WORK_PROVIDER": "jira",
        "JIRA_BASE_URL": "https://your-company.atlassian.net",
        "JIRA_EMAIL": "you@example.com",
        "JIRA_API_TOKEN": "your-token"
      }
    }
  }
}
```

Use your provider variables (`redmine`, `github`, `artia`) if you are not on Jira.

### 4. Tools (7)

This server is read/append only (least privilege). It does not create/edit/transition/assign/delete issues.

| Tool | Purpose | Main args |
|---|---|---|
| `whoami` | Validate auth and return identity | none |
| `search_tasks` | Find tasks | `query`, `native_query`, `max_results` |
| `get_task` | Compact task view | `task_id` |
| `add_comment` | Add comment | `task_id`, `comment` |
| `log_work` | Log one work entry | `task_id`, `time_spent`, `started?`, `comment?` |
| `log_work_batch` | Log multiple entries | `entries`, `skip_duplicates?` |
| `get_worklogs` | List worklogs | `task_id`, `mine_only?` |

Formats:
- `time_spent`: `2:40` or `1h 30m` / `45m` / `2h`
- `started`: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM`

### 5. Natural Language Examples

- "log 1h30m on PROJ-123 with comment 'fix X' today"
- "show my worklogs from PROJ-123"
- "add comment 'fix deployed' to PROJ-123"

For spreadsheet-like batch input, the agent should:
1. Use the provided date.
2. Parse each row into task + duration + comment.
3. Show a preview before execution.
4. Call `log_work_batch` and report skipped duplicates.

### 6. Fast Auth Check

```powershell
uv run python -c "from src.services.provider_registry import registry; print(registry.get().whoami())"
```

---

## Português

Guia rápido do servidor MCP para lançar e conferir horas em Jira Cloud, Redmine, GitHub e Artia a partir de agentes de IA.

### 1. Pré-requisitos

- `uv` instalado:
  `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- Conta no provedor com permissão para apontar horas.

### 2. Variáveis de ambiente

- Jira: `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_DAILY_JQL` (opcional)
- Redmine: `REDMINE_URL`, `REDMINE_API_KEY`
- GitHub: `GITHUB_TOKEN`, `GITHUB_REPO` (opcional)
- Artia: `ARTIA_CLIENT_ID`, `ARTIA_SECRET`, `ARTIA_ACCOUNT_ID`, `ARTIA_FOLDER_ID` (opcional)
- Seletor: `WORK_PROVIDER` (`jira`, `redmine`, `github`, `artia`)

Pode vir do `.env` ou do ambiente do cliente MCP.

### 3. Linkar com agentes (Claude, Codex, Cline)

Use a mesma ideia em qualquer cliente: iniciar este servidor por stdio com `uv --directory <repo> run server.py` e injetar variáveis `env`.

- Claude Code: use `claude mcp add ...`
- Claude Desktop: `claude_desktop_config.json` com `mcpServers`
- Codex: entrada MCP com `command` + `args` + `env`
- Cline: configuração MCP no VS Code com os mesmos campos

Blocos de `env` por provedor (copiar/colar):

- Esses blocos definem variáveis no processo/sessão atual do cliente.
- São úteis para teste rápido e troca temporária de provedor.
- Não é a mesma coisa que editar `.env`, que persiste valores em arquivo para reuso.
- Se ambos existirem, variáveis enviadas pelo cliente MCP normalmente têm precedência.

```json
{
  "WORK_PROVIDER": "jira",
  "JIRA_BASE_URL": "https://your-company.atlassian.net",
  "JIRA_EMAIL": "you@example.com",
  "JIRA_API_TOKEN": "your-token"
}
```

```json
{
  "WORK_PROVIDER": "redmine",
  "REDMINE_URL": "https://redmine.example.com",
  "REDMINE_API_KEY": "your-key"
}
```

```json
{
  "WORK_PROVIDER": "github",
  "GITHUB_TOKEN": "your-token",
  "GITHUB_REPO": "owner/repo"
}
```

```json
{
  "WORK_PROVIDER": "artia",
  "ARTIA_CLIENT_ID": "your-client-id",
  "ARTIA_SECRET": "your-secret",
  "ARTIA_ACCOUNT_ID": "your-account-id",
  "ARTIA_FOLDER_ID": "optional-folder-id"
}
```

### 4. Tools

`whoami`, `search_tasks`, `get_task`, `add_comment`, `log_work`, `log_work_batch`, `get_worklogs`.

### 5. Teste rápido

```powershell
uv run python -c "from src.services.provider_registry import registry; print(registry.get().whoami())"
```
