# jira-worklog-mcp

English documentation comes first because GitHub commonly presents repository content in English. A Portuguese version is available below.

- [English](#english)
- [Português](#portugues)

---

## English

`jira-worklog-mcp` is an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server for logging and checking Jira Cloud worklogs from AI agents such as Claude Code, Claude Desktop, Cursor, or any MCP client that supports stdio.

The main workflow is simple: paste time-sheet rows into your agent, review the preview, and let the agent call this server to log each work item in the right Jira issue.

### How It Works

```text
MCP client -> stdio JSON-RPC -> jira-worklog-mcp -> HTTPS -> Jira Cloud REST v3
```

- Transport: local stdio. No HTTP server and no open port.
- Auth: Jira Cloud basic auth with `JIRA_EMAIL` and `JIRA_API_TOKEN`.
- Config: loaded from environment variables, either from `.env` next to `server.py` or from the MCP client environment.
- Layers: `jira_client.py` handles Jira REST calls; `server.py` exposes FastMCP tools and human-friendly conversions.

### Tools

| Tool | Purpose |
|---|---|
| `jira_whoami` | Validates Jira authentication and returns the current identity when Jira allows it. |
| `jira_search_issues` | Searches issues. No args returns your open issues; `query` does text search; `jql` runs raw JQL. |
| `jira_resolve_daily_issue` | Resolves a daily issue using `JIRA_DAILY_SEARCH_TEXT` and optional `JIRA_DAILY_PROJECT`. |
| `jira_ensure_person_daily` | Checks whether a `<person> <month> de <year>` issue exists on the GREDOM board for the given month/year. Creates it and assigns it to the current user if not found. Triggered by the terms `daily` or `dayli`. |
| `jira_log_work` | Logs one worklog. `time_spent` accepts `2:40` or `1h 30m`. |
| `jira_log_work_batch` | Logs multiple worklogs in one call. Useful for time-sheet rows. |
| `jira_get_worklogs` | Lists worklogs from an issue. `mine_only` filters your entries when identity is available. |
| `jira_delete_worklog` | Deletes a worklog. Requires Jira permission for deleting worklogs. |

### Requirements

- [uv](https://github.com/astral-sh/uv), recommended for Python and dependency management.
- A Jira Cloud account with permission to log work on the target issues.
- A Jira API token from Atlassian.

Install `uv` on Windows:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Installation

```powershell
git clone <repo-url> jira-worklog-mcp
cd jira-worklog-mcp
cp .env.example .env
uv sync
```

Edit `.env` with your Jira URL, email, API token, and optional daily search template.

Do not commit `.env`. It is already ignored by `.gitignore`.

### Jira API Token

Create a token at:

```text
https://id.atlassian.com/manage-profile/security/api-tokens
```

Use an API token that can access the target Jira issues and worklog APIs. Store it in `JIRA_API_TOKEN`.

### Local Test

Start the server directly:

```powershell
uv run server.py
```

For a quick auth check:

```powershell
uv run python -c "import server; print(server.jira_whoami())"
```

### MCP Client Registration

Keep machine-specific paths outside Git. Define them as environment variables in your shell, OS profile, or MCP client environment:

```powershell
$env:UV_PATH = "C:/path/to/uv.exe"
$env:MCP_PROJECT_DIR = "C:/path/to/jira-worklog-mcp"
```

Claude Code:

```powershell
claude mcp add jira-worklog --scope user `
  -- $env:UV_PATH --directory $env:MCP_PROJECT_DIR run server.py
```

If you prefer passing Jira credentials through the MCP registration instead of `.env`:

```powershell
claude mcp add jira-worklog --scope user `
  -e JIRA_BASE_URL=https://your-company.atlassian.net `
  -e JIRA_EMAIL=you@example.com `
  -e JIRA_API_TOKEN=your-token `
  -e JIRA_DAILY_SEARCH_TEXT="Daily {month_name_en} {year}" `
  -e JIRA_DAILY_PROJECT=PROJ `
  -- $env:UV_PATH --directory $env:MCP_PROJECT_DIR run server.py
```

Claude Desktop, Cursor, or another stdio MCP client can launch through PowerShell so the local paths stay in environment variables:

```json
{
  "mcpServers": {
    "jira-worklog": {
      "command": "powershell",
      "args": [
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "& $env:UV_PATH --directory $env:MCP_PROJECT_DIR run server.py"
      ]
    }
  }
}
```

### Time-Sheet Workflow

The agent translates your pasted time-sheet block into tool calls. The server only exposes the primitives.

1. Use the reference date you provide. If none is provided, the agent should ask.
2. Classify each row:
   - Starts with an issue key like `PROJ-123`: log work to that issue.
   - Is a daily entry: call `jira_resolve_daily_issue`, which searches with `JIRA_DAILY_SEARCH_TEXT` and optionally filters by `JIRA_DAILY_PROJECT`.
   - Has no issue key and is not daily: skip it and report it in the preview.
3. Show a preview with issue key, duration, start time, and comment.
4. After confirmation, call `jira_log_work_batch` and report each result.

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `JIRA_BASE_URL` | yes | Jira Cloud URL, for example `https://your-company.atlassian.net`. |
| `JIRA_EMAIL` | yes | Atlassian account email. |
| `JIRA_API_TOKEN` | yes | Jira API token. |
| `JIRA_DAILY_SEARCH_TEXT` | no | Text/template used to find the issue when a row is daily, for example `Daily {month_name_en} {year}`. |
| `JIRA_DAILY_PROJECT` | no | Optional Jira project key filter for daily issue resolution. |
| `JIRA_DAILY_PERSON_NAME` | no | Person name used by `jira_ensure_person_daily` when none is passed explicitly, for example `John`. |

`JIRA_DAILY_SEARCH_TEXT` supports `{date}`, `{year}`, `{month}`, `{month_number}`, `{month_name_en}`, and `{month_name_pt}`.

Local launcher variables, used only in MCP client setup examples:

| Variable | Required | Description |
|---|---|---|
| `UV_PATH` | yes for absolute launcher setup | Absolute path to `uv.exe` or `uv`. |
| `MCP_PROJECT_DIR` | yes for absolute launcher setup | Absolute path to this repository on your machine. |

### Security

- Credentials are not stored in code.
- `.env` is ignored by Git.
- Local machine paths should stay in environment variables such as `UV_PATH` and `MCP_PROJECT_DIR`.
- The server uses local stdio transport; it does not open an inbound network port.
- The exposed tools are limited to searching issues and managing worklogs.

### Development

```powershell
uv run pytest -q
```

Tests use [`respx`](https://lundberg.github.io/respx/) to mock Jira HTTP calls. They do not call the real Jira API.

Project layout:

```text
jira-worklog-mcp/
  pyproject.toml
  .env.example
  server.py
  jira_client.py
  tests/
```

### Troubleshooting

**The MCP client shows the server as failed.**

Run `uv run server.py` from the repository and check the error. Common causes are missing environment variables, `uv` not available to the launcher, or an incorrect `MCP_PROJECT_DIR`.

**`jira_whoami` returns an invalid token error.**

Check `JIRA_BASE_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN`. Generate a new token if needed.

**A worklog was created but does not appear in the company timesheet.**

Your company may use a separate timesheet app such as Tempo Timesheets. This server writes native Jira worklogs.

---

## Português

`jira-worklog-mcp` é um servidor [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) para lançar e conferir horas no Jira Cloud a partir de agentes de IA como Claude Code, Claude Desktop, Cursor ou qualquer cliente MCP via stdio.

O fluxo principal é simples: cole as linhas da sua planilha de horas no agente, confira o preview, e deixe o agente chamar este servidor para registrar cada item na issue correta do Jira.

### Como Funciona

```text
Cliente MCP -> stdio JSON-RPC -> jira-worklog-mcp -> HTTPS -> Jira Cloud REST v3
```

- Transporte: stdio local. Sem servidor HTTP e sem porta aberta.
- Auth: basic auth do Jira Cloud com `JIRA_EMAIL` e `JIRA_API_TOKEN`.
- Configuração: vem de variáveis de ambiente, lidas do `.env` ao lado do `server.py` ou passadas pelo cliente MCP.
- Camadas: `jira_client.py` fala com a REST do Jira; `server.py` expõe as tools FastMCP e faz conversões amigáveis.

### Tools

| Tool | Finalidade |
|---|---|
| `jira_whoami` | Valida a autenticação no Jira e retorna a identidade atual quando o Jira permite. |
| `jira_search_issues` | Busca issues. Sem args retorna suas abertas; `query` faz busca textual; `jql` executa JQL cru. |
| `jira_resolve_daily_issue` | Resolve uma issue de daily usando `JIRA_DAILY_SEARCH_TEXT` e `JIRA_DAILY_PROJECT` opcional. |
| `jira_ensure_person_daily` | Verifica se existe uma issue `<pessoa> <mês> de <ano>` no quadro GREDOM para o mês/ano informado. Se não existir, cria e atribui ao usuário atual. Acionada pelos termos `daily` ou `dayli`. |
| `jira_log_work` | Lança um worklog. `time_spent` aceita `2:40` ou `1h 30m`. |
| `jira_log_work_batch` | Lança vários worklogs em uma chamada. Bom para linhas de planilha. |
| `jira_get_worklogs` | Lista worklogs de uma issue. `mine_only` filtra os seus quando a identidade está disponível. |
| `jira_delete_worklog` | Apaga um worklog. Requer permissão no Jira para apagar worklogs. |

### Pré-Requisitos

- [uv](https://github.com/astral-sh/uv), recomendado para gerenciar Python e dependências.
- Conta no Jira Cloud com permissão para lançar horas nas issues.
- API token do Jira criado na Atlassian.

Instale o `uv` no Windows:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Instalação

```powershell
git clone <url-do-repo> jira-worklog-mcp
cd jira-worklog-mcp
cp .env.example .env
uv sync
```

Edite o `.env` com a URL do Jira, email, token e, se precisar, o texto/template de busca da daily.

Não commite o `.env`. Ele já está no `.gitignore`.

### Token De API Do Jira

Crie o token em:

```text
https://id.atlassian.com/manage-profile/security/api-tokens
```

Use um token que consiga acessar as issues e APIs de worklog desejadas. Salve em `JIRA_API_TOKEN`.

### Teste Local

Suba o servidor diretamente:

```powershell
uv run server.py
```

Para testar auth rapidamente:

```powershell
uv run python -c "import server; print(server.jira_whoami())"
```

### Registro Em Cliente MCP

Mantenha caminhos específicos da sua máquina fora do Git. Defina-os como variáveis de ambiente no shell, no perfil do sistema ou no ambiente do cliente MCP:

```powershell
$env:UV_PATH = "C:/caminho/para/uv.exe"
$env:MCP_PROJECT_DIR = "C:/caminho/para/jira-worklog-mcp"
```

Claude Code:

```powershell
claude mcp add jira-worklog --scope user `
  -- $env:UV_PATH --directory $env:MCP_PROJECT_DIR run server.py
```

Se preferir passar as credenciais pelo registro MCP em vez do `.env`:

```powershell
claude mcp add jira-worklog --scope user `
  -e JIRA_BASE_URL=https://sua-empresa.atlassian.net `
  -e JIRA_EMAIL=voce@example.com `
  -e JIRA_API_TOKEN=seu-token `
  -e JIRA_DAILY_SEARCH_TEXT="Daily {month_name_pt} {year}" `
  -e JIRA_DAILY_PROJECT=PROJ `
  -- $env:UV_PATH --directory $env:MCP_PROJECT_DIR run server.py
```

Claude Desktop, Cursor ou outro cliente MCP via stdio pode chamar pelo PowerShell para manter os caminhos em variáveis de ambiente:

```json
{
  "mcpServers": {
    "jira-worklog": {
      "command": "powershell",
      "args": [
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "& $env:UV_PATH --directory $env:MCP_PROJECT_DIR run server.py"
      ]
    }
  }
}
```

### Fluxo Da Planilha

O agente traduz o bloco colado da planilha em chamadas de tools. O servidor apenas expõe as primitivas.

1. Usa a data de referência que você informar. Se não informar, o agente deve perguntar.
2. Classifica cada linha:
   - Começa com chave de issue, como `PROJ-123`: lança na issue.
   - É uma daily: chama `jira_resolve_daily_issue`, que busca usando `JIRA_DAILY_SEARCH_TEXT` e filtra opcionalmente por `JIRA_DAILY_PROJECT`.
   - Não tem chave e não é daily: pula e mostra no preview.
3. Mostra preview com issue, duração, início e comentário.
4. Depois da confirmação, chama `jira_log_work_batch` e reporta cada resultado.

### Variáveis De Ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `JIRA_BASE_URL` | sim | URL do Jira Cloud, por exemplo `https://sua-empresa.atlassian.net`. |
| `JIRA_EMAIL` | sim | Email da conta Atlassian. |
| `JIRA_API_TOKEN` | sim | API token do Jira. |
| `JIRA_DAILY_SEARCH_TEXT` | não | Texto/template usado para achar a issue quando uma linha for daily, por exemplo `Daily {month_name_pt} {year}`. |
| `JIRA_DAILY_PROJECT` | não | Filtro opcional de chave de projeto para resolver a issue de daily. |
| `JIRA_DAILY_PERSON_NAME` | não | Nome da pessoa usado por `jira_ensure_person_daily` quando não passado explicitamente, por exemplo `João`. |

`JIRA_DAILY_SEARCH_TEXT` aceita `{date}`, `{year}`, `{month}`, `{month_number}`, `{month_name_en}` e `{month_name_pt}`.

Variáveis locais de launcher, usadas apenas nos exemplos de registro MCP:

| Variável | Obrigatória | Descrição |
|---|---|---|
| `UV_PATH` | sim para setup com caminho absoluto | Caminho absoluto para `uv.exe` ou `uv`. |
| `MCP_PROJECT_DIR` | sim para setup com caminho absoluto | Caminho absoluto deste repositório na sua máquina. |

### Segurança

- Credenciais não ficam no código.
- `.env` é ignorado pelo Git.
- Caminhos locais da máquina devem ficar em variáveis como `UV_PATH` e `MCP_PROJECT_DIR`.
- O servidor usa stdio local; não abre porta de rede.
- As tools expostas se limitam a buscar issues e gerenciar worklogs.

### Desenvolvimento

```powershell
uv run pytest -q
```

Os testes usam [`respx`](https://lundberg.github.io/respx/) para mockar chamadas HTTP ao Jira. Eles não chamam a API real.

Estrutura:

```text
jira-worklog-mcp/
  pyproject.toml
  .env.example
  server.py
  jira_client.py
  tests/
```

### Troubleshooting

**O cliente MCP mostra o servidor como failed.**

Rode `uv run server.py` no repositório e veja o erro. Causas comuns: variáveis de ambiente ausentes, `uv` indisponível para o launcher ou `MCP_PROJECT_DIR` incorreto.

**`jira_whoami` retorna erro de token inválido.**

Confira `JIRA_BASE_URL`, `JIRA_EMAIL` e `JIRA_API_TOKEN`. Gere um token novo se necessário.

**A hora foi lançada mas não aparece no timesheet da empresa.**

Sua empresa pode usar um app separado, como Tempo Timesheets. Este servidor grava worklogs nativos do Jira.
