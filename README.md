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
- Layers: `src/jira_client.py` handles Jira REST calls; `src/providers/` adapts them behind a provider interface; `src/tools/` exposes FastMCP tools; `src/server.py` wires them together. The root `server.py` is a thin launcher.

### Tools

This server is **read/append only** by design (least privilege). It exposes exactly seven tools and has **no** ability to create, edit, transition, assign, or delete issues, comments, or worklogs.

| Tool | Purpose |
|---|---|
| `jira_whoami` | Validates Jira authentication and returns the current identity when Jira allows it. |
| `jira_search_issues` | Searches issues. No args returns your open issues; `query` does text search; `jql` runs raw JQL. |
| `jira_get_issue` | Returns a compact view of one issue (key, summary, status, type, assignee, priority, labels, description text). |
| `jira_add_comment` | Adds a comment to an issue. Plain text is converted to Jira ADF. |
| `jira_log_work` | Logs one worklog. `time_spent` accepts `2:40` or `1h 30m`. `issue_key="daily"` logs into the configured monthly bucket (`JIRA_DAILY_JQL`). |
| `jira_log_work_batch` | Logs multiple worklogs in one call. Entries may use `issue_key="daily"`. Skips entries already logged at the same date/time and returns them for confirmation. |
| `jira_get_worklogs` | Lists worklogs from an issue. `mine_only` filters your entries when identity is available. |

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

Edit `.env` with your Jira URL, email, and API token.

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
   - Has no issue key: find it first with `jira_search_issues`, or skip it and report it in the preview.
3. Show a preview with issue key, duration, start time, and comment.
4. After confirmation, call `jira_log_work_batch`. Entries that already have a worklog at the same date/time are skipped and returned under `skipped_duplicates`; decide per entry whether to log them anyway with `jira_log_work`.

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `JIRA_BASE_URL` | yes | Jira Cloud URL, must be HTTPS and a `*.atlassian.net` host, for example `https://your-company.atlassian.net`. |
| `JIRA_EMAIL` | yes | Atlassian account email. |
| `JIRA_API_TOKEN` | yes | Jira API token. |
| `JIRA_DAILY_JQL` | no | JQL that resolves `issue_key="daily"` to a recurring monthly bucket issue. Use `{month}` (Portuguese month name) and `{year}`, filled from the worklog date, e.g. `project = MYPROJ AND summary ~ "Timesheet {month} de {year}" ORDER BY created DESC`. Unset disables the feature. |

The required three are read from `.env` (optional) or from the MCP client environment. No `.env` file is required.

Local launcher variables, used only in MCP client setup examples:

| Variable | Required | Description |
|---|---|---|
| `UV_PATH` | yes for absolute launcher setup | Absolute path to `uv.exe` or `uv`. |
| `MCP_PROJECT_DIR` | yes for absolute launcher setup | Absolute path to this repository on your machine. |

### Security

- **Least privilege:** the server is read/append only. It cannot create, edit, transition, assign, or delete issues, comments, or worklogs. No tool maps to a destructive Jira endpoint.
- `JIRA_BASE_URL` is validated: HTTPS only and limited to `*.atlassian.net` hosts.
- Credentials are not stored in code. They come from environment variables; `.env` is optional and ignored by Git.
- One shared, pooled `httpx.Client` with a fixed timeout and connection limits.
- Local machine paths should stay in environment variables such as `UV_PATH` and `MCP_PROJECT_DIR`.
- The server uses local stdio transport; it does not open an inbound network port.

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
  server.py            # thin launcher -> src/server.py
  src/
    server.py          # FastMCP app, registers tools
    config.py          # loads .env, selects provider
    jira_client.py     # Jira REST v3 HTTP client
    utils.py
    models/            # Task, Comment, Worklog, ProviderCapabilities
    providers/         # base (TaskProvider) + jira_provider
    services/          # provider_registry
    tools/             # one module per MCP tool
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
- Camadas: `src/jira_client.py` fala com a REST do Jira; `src/providers/` adapta para uma interface de provider; `src/tools/` expõe as tools FastMCP; `src/server.py` liga tudo. O `server.py` da raiz é só um launcher.

### Tools

Este servidor é **somente leitura/append** por design (menor privilégio). Expõe exatamente sete tools e **não** consegue criar, editar, transicionar, atribuir ou apagar issues, comentários ou worklogs.

| Tool | Finalidade |
|---|---|
| `jira_whoami` | Valida a autenticação no Jira e retorna a identidade atual quando o Jira permite. |
| `jira_search_issues` | Busca issues. Sem args retorna suas abertas; `query` faz busca textual; `jql` executa JQL cru. |
| `jira_get_issue` | Retorna uma visão compacta de uma issue (key, summary, status, tipo, responsável, prioridade, labels, texto da descrição). |
| `jira_add_comment` | Adiciona um comentário a uma issue. Texto simples é convertido para ADF do Jira. |
| `jira_log_work` | Lança um worklog. `time_spent` aceita `2:40` ou `1h 30m`. `issue_key="daily"` lança na tarefa-balde mensal configurada (`JIRA_DAILY_JQL`). |
| `jira_log_work_batch` | Lança vários worklogs em uma chamada. Entradas podem usar `issue_key="daily"`. Pula lançamentos já existentes no mesmo dia/horário e os devolve para você confirmar. |
| `jira_get_worklogs` | Lista worklogs de uma issue. `mine_only` filtra os seus quando a identidade está disponível. |

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

Edite o `.env` com a URL do Jira, email e token.

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
   - Não tem chave: acha a issue antes com `jira_search_issues`, ou pula e mostra no preview.
3. Mostra preview com issue, duração, início e comentário.
4. Depois da confirmação, chama `jira_log_work_batch`. Lançamentos já existentes no mesmo dia/horário são pulados e devolvidos em `skipped_duplicates`; você decide por linha se quer lançar mesmo assim via `jira_log_work`.

### Variáveis De Ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `JIRA_BASE_URL` | sim | URL do Jira Cloud, precisa ser HTTPS e um host `*.atlassian.net`, por exemplo `https://sua-empresa.atlassian.net`. |
| `JIRA_EMAIL` | sim | Email da conta Atlassian. |
| `JIRA_API_TOKEN` | sim | API token do Jira. |
| `JIRA_DAILY_JQL` | não | JQL que resolve `issue_key="daily"` para a tarefa-balde mensal. Use `{month}` (nome do mês em PT) e `{year}`, preenchidos pela data do worklog, ex. `project = MYPROJ AND summary ~ "Timesheet {month} de {year}" ORDER BY created DESC`. Vazio desliga o recurso. |

As três obrigatórias são lidas do `.env` (opcional) ou do ambiente do cliente MCP. Nenhum arquivo `.env` é obrigatório.

Variáveis locais de launcher, usadas apenas nos exemplos de registro MCP:

| Variável | Obrigatória | Descrição |
|---|---|---|
| `UV_PATH` | sim para setup com caminho absoluto | Caminho absoluto para `uv.exe` ou `uv`. |
| `MCP_PROJECT_DIR` | sim para setup com caminho absoluto | Caminho absoluto deste repositório na sua máquina. |

### Segurança

- **Menor privilégio:** o servidor é somente leitura/append. Não cria, edita, transiciona, atribui nem apaga issues, comentários ou worklogs. Nenhuma tool aponta para um endpoint destrutivo do Jira.
- `JIRA_BASE_URL` é validada: apenas HTTPS e apenas hosts `*.atlassian.net`.
- Credenciais não ficam no código. Vêm de variáveis de ambiente; `.env` é opcional e ignorado pelo Git.
- Um único `httpx.Client` compartilhado e com pool, timeout fixo e limites de conexão.
- Caminhos locais da máquina devem ficar em variáveis como `UV_PATH` e `MCP_PROJECT_DIR`.
- O servidor usa stdio local; não abre porta de rede.

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
  server.py            # launcher fino -> src/server.py
  src/
    server.py          # app FastMCP, registra as tools
    config.py          # carrega .env, seleciona o provider
    jira_client.py     # cliente HTTP da REST v3 do Jira
    utils.py
    models/            # Task, Comment, Worklog, ProviderCapabilities
    providers/         # base (TaskProvider) + jira_provider
    services/          # provider_registry
    tools/             # um módulo por tool MCP
  tests/
```

### Troubleshooting

**O cliente MCP mostra o servidor como failed.**

Rode `uv run server.py` no repositório e veja o erro. Causas comuns: variáveis de ambiente ausentes, `uv` indisponível para o launcher ou `MCP_PROJECT_DIR` incorreto.

**`jira_whoami` retorna erro de token inválido.**

Confira `JIRA_BASE_URL`, `JIRA_EMAIL` e `JIRA_API_TOKEN`. Gere um token novo se necessário.

**A hora foi lançada mas não aparece no timesheet da empresa.**

Sua empresa pode usar um app separado, como Tempo Timesheets. Este servidor grava worklogs nativos do Jira.
