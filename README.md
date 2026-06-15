# worklog-mcp

English documentation comes first because GitHub commonly presents repository content in English. A Portuguese version is available below.

- [English](#english)
- [Português](#portugues)

---

## English

`worklog-mcp` is an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server for logging and checking worklogs from multiple task management providers (Jira Cloud, Redmine, GitHub, Artia) using AI agents such as Claude Code, Claude Desktop, Cursor, or any MCP client that supports stdio.

The main workflow is simple: paste time-sheet rows into your agent, review the preview, and let the agent call this server to log each work item in the right issue on your preferred provider.

### How It Works

```text
MCP client -> stdio JSON-RPC -> worklog-mcp -> HTTPS -> Task Provider API
                                              (Jira Cloud, Redmine, GitHub, Artia)
```

- Transport: local stdio. No HTTP server and no open port.
- Providers: select your task management system via `WORK_PROVIDER` env variable (default: `jira`).
- Auth: provider-specific credentials from environment variables or `.env`.
- Config: loaded from `.env` (optional) or from the MCP client environment.
- Layers: client modules (`src/jira_client.py`, `src/redmine_client.py`, etc.) handle provider-specific API calls; `src/providers/` adapts them behind a common `TaskProvider` interface; `src/tools/` exposes FastMCP tools; `src/server.py` wires them together. The root `server.py` is a thin launcher.

### Tools

This server exposes exactly seven tools. Availability and behavior depend on the selected provider and its capabilities. By design, all tools are read/append only (least privilege) — no ability to create, edit, transition, assign, or delete issues, comments, or worklogs.

| Tool | Purpose | Notes |
|---|---|---|
| `whoami` | Validates authentication and returns the current identity when the provider allows it. | Available on all providers. |
| `search_tasks` | Searches tasks. No args returns your open/assigned tasks; `query` does text search; `native_query` runs provider-specific syntax (JQL for Jira, etc.). | Available on all providers. |
| `get_task` | Returns a compact view of one task (key, summary, status, type, assignee, priority, labels, description text). | Available on all providers. |
| `add_comment` | Adds a comment to a task. Plain text is converted to provider-specific format (ADF for Jira, markdown for GitHub, etc.). | Depends on provider capabilities. |
| `log_work` | Logs one worklog. `time_spent` accepts `2:40` or `1h 30m`. Provider-specific extras like `issue_key="daily"` (Jira) may apply. | Depends on provider capabilities. |
| `log_work_batch` | Logs multiple worklogs in one call. Skips entries already logged at the same date/time and returns them for confirmation. | Depends on provider capabilities. |
| `get_worklogs` | Lists worklogs from a task. `mine_only` filters your entries when identity is available. | Depends on provider capabilities. |

### Requirements

- [uv](https://github.com/astral-sh/uv), recommended for Python and dependency management.
- An account on your chosen provider (Jira Cloud, Redmine, GitHub, or Artia) with permission to log work on target tasks.
- API token or credentials for your provider (varies by provider).

Install `uv` on Windows:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Supported Providers

- **Jira Cloud** (`jira`): Log work on Jira issues. Supports daily bucket feature via JQL template.
- **Redmine** (`redmine`): Log work on Redmine issues.
- **GitHub** (`github`): Log work on GitHub issues and pull requests.
- **Artia** (`artia`): Log work on Artia tasks.

### Installation

```powershell
git clone https://github.com/luizeduul/mcp-worklog-reg.git
cd worklog-mcp
cp .env.example .env
uv sync
```

Edit `.env` with credentials for your selected provider.

Do not commit `.env`. It is already ignored by `.gitignore`.

### Provider-Specific Setup

#### Jira Cloud

1. Create a Jira API token at: https://id.atlassian.com/manage-profile/security/api-tokens
2. Store the token in `JIRA_API_TOKEN` env variable or `.env` file.
3. Set `WORK_PROVIDER=jira` and configure `JIRA_BASE_URL`, `JIRA_EMAIL`.

#### Redmine

1. Log in to Redmine and go to your Account settings.
2. Generate or copy your API key from the right sidebar.
3. Store in `REDMINE_API_KEY` and configure `REDMINE_URL`.
4. Set `WORK_PROVIDER=redmine`.

#### GitHub

1. Create a personal access token at: https://github.com/settings/tokens
2. Grant permissions: `repo`, `user` scopes.
3. Store in `GITHUB_TOKEN` env variable.
4. Set `WORK_PROVIDER=github`.

#### Artia

1. Generate integration keys in Artia (ClientId + Secret).
2. Store in `ARTIA_CLIENT_ID` and `ARTIA_SECRET`.
3. Configure `ARTIA_API_URL` (optional; default is `https://api.artia.com/graphql`).
4. Set `ARTIA_ACCOUNT_ID` (required) and optionally `ARTIA_FOLDER_ID`.
3. Set `WORK_PROVIDER=artia`.

### Local Test

Start the server directly:

```powershell
uv run server.py
```

For a quick auth check on the active provider:

```powershell
uv run python -c "from src.services.provider_registry import registry; print(registry.get().whoami())"
```

To test a different provider, set `WORK_PROVIDER`:

```powershell
$env:WORK_PROVIDER = "redmine"
uv run python -c "from src.services.provider_registry import registry; print(registry.get().whoami())"
```

### MCP Client Registration

Keep machine-specific paths outside Git. Define them as environment variables in your shell, OS profile, or MCP client environment:

```powershell
$env:UV_PATH = "C:/path/to/uv.exe"
$env:MCP_PROJECT_DIR = "C:/path/to/worklog-mcp"
$env:WORK_PROVIDER = "jira"  # or redmine, github, artia
```

**Example: Register with Jira provider via Claude Code**

```powershell
claude mcp add worklog --scope user `
  -e WORK_PROVIDER=jira `
  -e JIRA_BASE_URL=https://your-company.atlassian.net `
  -e JIRA_EMAIL=you@example.com `
  -e JIRA_API_TOKEN=your-token `
  -- $env:UV_PATH --directory $env:MCP_PROJECT_DIR run server.py
```

**Example: Register with Redmine provider**

```powershell
claude mcp add worklog --scope user `
  -e WORK_PROVIDER=redmine `
  -e REDMINE_URL=https://redmine.example.com `
  -e REDMINE_API_KEY=your-key `
  -- $env:UV_PATH --directory $env:MCP_PROJECT_DIR run server.py
```

**Claude Desktop, Cursor, or another stdio MCP client configuration**

Create or edit `%APPDATA%\Claude\claude_desktop_config.json` (on Windows):

```json
{
  "mcpServers": {
    "worklog": {
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

Alternatively, use `.env` file in the repository root instead of passing credentials via environment.

### Time-Sheet Workflow

The agent translates your pasted time-sheet block into tool calls. The server only exposes the primitives.

1. Use the reference date you provide. If none is provided, the agent should ask.
2. Classify each row:
   - Starts with a task key like `PROJ-123`: log work to that task.
   - Has no task key: find it first with `search_tasks`, or skip it and report it in the preview.
3. Show a preview with task key, duration, start time, and comment.
4. After confirmation, call `log_work_batch`. Entries that already have a worklog at the same date/time are skipped and returned under `skipped_duplicates`; decide per entry whether to log them anyway with `log_work`.

**Note:** Provider-specific features like Jira's `issue_key="daily"` are handled automatically by the server.

### Environment Variables

#### Provider Selection

| Variable | Default | Description |
|---|---|---|
| `WORK_PROVIDER` | `jira` | Active provider: `jira`, `redmine`, `github`, or `artia`. |

#### Jira Cloud (when `WORK_PROVIDER=jira`)

| Variable | Required | Description |
|---|---|---|
| `JIRA_BASE_URL` | yes | Jira Cloud URL, must be HTTPS and a `*.atlassian.net` host, for example `https://your-company.atlassian.net`. |
| `JIRA_EMAIL` | yes | Atlassian account email. |
| `JIRA_API_TOKEN` | yes | Jira API token. |
| `JIRA_DAILY_JQL` | no | JQL that resolves `issue_key="daily"` to a recurring monthly bucket issue. Use `{month}` (Portuguese month name) and `{year}`, filled from the worklog date, e.g. `project = MYPROJ AND summary ~ "Timesheet {month} de {year}" ORDER BY created DESC`. Unset disables the feature. |

#### Redmine (when `WORK_PROVIDER=redmine`)

| Variable | Required | Description |
|---|---|---|
| `REDMINE_URL` | yes | Redmine base URL, e.g. `https://redmine.example.com`. |
| `REDMINE_API_KEY` | yes | Redmine API key. |

#### GitHub (when `WORK_PROVIDER=github`)

| Variable | Required | Description |
|---|---|---|
| `GITHUB_TOKEN` | yes | GitHub personal access token (PAT). |

#### Artia (when `WORK_PROVIDER=artia`)

| Variable | Required | Description |
|---|---|---|
| `ARTIA_API_URL` | no | Artia GraphQL URL. Default: `https://api.artia.com/graphql`. |
| `ARTIA_CLIENT_ID` | yes | Artia integration ClientId. |
| `ARTIA_SECRET` | yes | Artia integration Secret. |
| `ARTIA_ACCOUNT_ID` | yes | Account/workspace id used for get_task/worklogs. |
| `ARTIA_FOLDER_ID` | no | Default folder id for `search_tasks`. |
| `ARTIA_WORKLOG_STATUS_ID` | no | Optional status id sent when creating a time entry. |

The required variables for your chosen provider are read from `.env` (optional) or from the MCP client environment. No `.env` file is required.

### Security

- **Least privilege:** the server is read/append only. It cannot create, edit, transition, assign, or delete tasks, comments, or worklogs. No tool maps to a destructive endpoint.
- **Provider URLs validated:** Only HTTPS URLs are accepted. Provider URLs (Jira, Redmine, etc.) are validated for correctness.
- **Credentials not stored in code:** They come from environment variables; `.env` is optional and ignored by Git.
- **One shared, pooled HTTP client** with fixed timeout and connection limits per provider instance.
- **Local machine paths** should stay in environment variables such as `UV_PATH` and `MCP_PROJECT_DIR`.
- **Local stdio transport:** the server does not open an inbound network port.

### Development

```powershell
uv run pytest -q
```

Tests use [`respx`](https://lundberg.github.io/respx/) to mock HTTP calls to various providers. They do not call real provider APIs.

Project layout:

```text
worklog-mcp/
  pyproject.toml
  .env.example
  server.py                      # thin launcher -> src/server.py
  src/
    server.py                    # FastMCP app, registers tools
    config.py                    # loads .env, selects provider
    jira_client.py               # Jira REST v3 HTTP client
    redmine_client.py            # Redmine API client
    github_client.py             # GitHub REST API client
    artia_client.py              # Artia API client
    utils.py
    models/                      # Task, Comment, Worklog, ProviderCapabilities
    providers/
      base.py                    # TaskProvider protocol and BaseProvider
      jira_provider.py           # Jira Cloud provider
      redmine_provider.py        # Redmine provider
      github_provider.py         # GitHub provider
      artia_provider.py          # Artia provider
    services/
      provider_registry.py       # lazily-built provider instances
    tools/                       # one module per MCP tool
  tests/
```

### Architecture

- **Provider interface** (`src/providers/base.py`): `TaskProvider` protocol defines the contract. Each provider implements required methods (`whoami`, `search_tasks`, `get_task`) and optional ones gated by `capabilities` (`add_comment`, `log_work`, `get_worklogs`).
- **Provider registry** (`src/services/provider_registry.py`): Lazily instantiates and caches provider instances based on `WORK_PROVIDER` env variable.
- **Tools** (`src/tools/`): Seven FastMCP tools that call the active provider through the registry.

### Troubleshooting

**The MCP client shows the server as failed.**

Run `uv run server.py` from the repository and check the error. Common causes are missing environment variables, `uv` not available to the launcher, or an incorrect `MCP_PROJECT_DIR`.

**Authentication fails with invalid credentials error.**

Check that you are using the correct provider and that the credentials are valid:
- For Jira: `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`.
- For Redmine: `REDMINE_URL`, `REDMINE_API_KEY`.
- For GitHub: `GITHUB_TOKEN`.
- For Artia: `ARTIA_CLIENT_ID`, `ARTIA_SECRET`, `ARTIA_ACCOUNT_ID`.

Generate a new token if needed.

**Worklog was created on one provider but I expected another.**

Check the `WORK_PROVIDER` environment variable. Default is `jira`. Set it explicitly if needed.

**A worklog was created but does not appear in the company timesheet.**

Your company may use a separate timesheet app (e.g., Tempo Timesheets for Jira, etc.). This server writes native provider worklogs.

---

## Português

`worklog-mcp` é um servidor [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) para lançar e conferir horas em múltiplos provedores de gestão de tarefas (Jira Cloud, Redmine, GitHub, Artia) a partir de agentes de IA como Claude Code, Claude Desktop, Cursor ou qualquer cliente MCP via stdio.

O fluxo principal é simples: cole as linhas da sua planilha de horas no agente, confira o preview, e deixe o agente chamar este servidor para registrar cada item na ferramenta correta.

### Como Funciona

```text
Cliente MCP -> stdio JSON-RPC -> worklog-mcp -> HTTPS -> API do Provedor
                                            (Jira Cloud, Redmine, GitHub, Artia)
```

- Transporte: stdio local. Sem servidor HTTP e sem porta aberta.
- Provedores: selecione sua ferramenta via variável `WORK_PROVIDER` (padrão: `jira`).
- Autenticação: credenciais específicas do provedor de variáveis de ambiente ou `.env`.
- Configuração: vem de variáveis de ambiente, lidas do `.env` (opcional) ou passadas pelo cliente MCP.
- Camadas: módulos de cliente (`src/jira_client.py`, `src/redmine_client.py`, etc.) conversam com APIs específicas; `src/providers/` adapta para uma interface comum `TaskProvider`; `src/tools/` expõe as tools FastMCP; `src/server.py` liga tudo. O `server.py` da raiz é só um launcher.

### Tools

Este servidor expõe exatamente sete tools. A disponibilidade e comportamento dependem do provedor selecionado e suas capacidades. Por design, todas as tools são somente leitura/append (menor privilégio) — não conseguem criar, editar, transicionar, atribuir nem apagar tarefas, comentários ou worklogs.

| Tool | Finalidade | Notas |
|---|---|---|
| `whoami` | Valida a autenticação e retorna a identidade atual quando o provedor permite. | Disponível em todos os provedores. |
| `search_tasks` | Busca tarefas. Sem args retorna suas abertas/atribuídas; `query` faz busca textual; `native_query` executa sintaxe específica do provedor (JQL para Jira, etc.). | Disponível em todos os provedores. |
| `get_task` | Retorna uma visão compacta de uma tarefa (chave, resumo, status, tipo, responsável, prioridade, labels, texto da descrição). | Disponível em todos os provedores. |
| `add_comment` | Adiciona um comentário a uma tarefa. Texto simples é convertido para formato específico do provedor (ADF para Jira, markdown para GitHub, etc.). | Depende das capacidades do provedor. |
| `log_work` | Lança um worklog. `time_spent` aceita `2:40` ou `1h 30m`. Extras específicos do provedor como `issue_key="daily"` (Jira) podem ser aplicados. | Depende das capacidades do provedor. |
| `log_work_batch` | Lança vários worklogs em uma chamada. Pula lançamentos já existentes no mesmo dia/horário e os devolve para confirmação. | Depende das capacidades do provedor. |
| `get_worklogs` | Lista worklogs de uma tarefa. `mine_only` filtra os seus quando a identidade está disponível. | Depende das capacidades do provedor. |

### Pré-Requisitos

- [uv](https://github.com/astral-sh/uv), recomendado para gerenciar Python e dependências.
- Conta em seu provedor escolhido (Jira Cloud, Redmine, GitHub ou Artia) com permissão para lançar horas nas tarefas.
- API token ou credenciais para seu provedor (varia por provedor).

Instale o `uv` no Windows:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Provedores Suportados

- **Jira Cloud** (`jira`): Lança horas em issues do Jira. Suporta feature de tarefa-balde diária via template JQL.
- **Redmine** (`redmine`): Lança horas em issues do Redmine.
- **GitHub** (`github`): Lança horas em issues e pull requests do GitHub.
- **Artia** (`artia`): Lança horas em tarefas do Artia.

### Instalação

```powershell
git clone https://github.com/luizeduul/mcp-worklog-reg.git
cd worklog-mcp
cp .env.example .env
uv sync
```

Edite o `.env` com as credenciais do provedor selecionado.

Não commite o `.env`. Ele já está no `.gitignore`.

### Setup Específico Do Provedor

#### Jira Cloud

1. Crie um token API do Jira em: https://id.atlassian.com/manage-profile/security/api-tokens
2. Guarde o token em `JIRA_API_TOKEN` ou no arquivo `.env`.
3. Configure `WORK_PROVIDER=jira` e defina `JIRA_BASE_URL`, `JIRA_EMAIL`.

#### Redmine

1. Faça login no Redmine e vá para Configurações da Conta.
2. Gere ou copie sua chave API da barra lateral direita.
3. Guarde em `REDMINE_API_KEY` e configure `REDMINE_URL`.
4. Configure `WORK_PROVIDER=redmine`.

#### GitHub

1. Crie um token de acesso pessoal em: https://github.com/settings/tokens
2. Conceda permissões: escopos `repo` e `user`.
3. Guarde em `GITHUB_TOKEN`.
4. Configure `WORK_PROVIDER=github`.

#### Artia

1. Gere chaves de integração no Artia (ClientId + Secret).
2. Guarde em `ARTIA_CLIENT_ID` e `ARTIA_SECRET`.
3. Configure `ARTIA_API_URL` (opcional; padrão `https://api.artia.com/graphql`).
4. Defina `ARTIA_ACCOUNT_ID` (obrigatório) e opcionalmente `ARTIA_FOLDER_ID`.
3. Configure `WORK_PROVIDER=artia`.

### Teste Local

Suba o servidor diretamente:

```powershell
uv run server.py
```

Para testar autenticação rapidamente no provedor ativo:

```powershell
uv run python -c "from src.services.provider_registry import registry; print(registry.get().whoami())"
```

Para testar um provedor diferente, configure `WORK_PROVIDER`:

```powershell
$env:WORK_PROVIDER = "redmine"
uv run python -c "from src.services.provider_registry import registry; print(registry.get().whoami())"
```

### Registro Em Cliente MCP

Mantenha caminhos específicos da sua máquina fora do Git. Defina-os como variáveis de ambiente no shell, no perfil do sistema ou no ambiente do cliente MCP:

```powershell
$env:UV_PATH = "C:/caminho/para/uv.exe"
$env:MCP_PROJECT_DIR = "C:/caminho/para/worklog-mcp"
$env:WORK_PROVIDER = "jira"  # ou redmine, github, artia
```

**Exemplo: Registrar com provedor Jira via Claude Code**

```powershell
claude mcp add worklog --scope user `
  -e WORK_PROVIDER=jira `
  -e JIRA_BASE_URL=https://sua-empresa.atlassian.net `
  -e JIRA_EMAIL=voce@example.com `
  -e JIRA_API_TOKEN=seu-token `
  -- $env:UV_PATH --directory $env:MCP_PROJECT_DIR run server.py
```

**Exemplo: Registrar com provedor Redmine**

```powershell
claude mcp add worklog --scope user `
  -e WORK_PROVIDER=redmine `
  -e REDMINE_URL=https://redmine.example.com `
  -e REDMINE_API_KEY=sua-chave `
  -- $env:UV_PATH --directory $env:MCP_PROJECT_DIR run server.py
```

**Claude Desktop, Cursor ou outro cliente MCP via stdio**

Edite `%APPDATA%\Claude\claude_desktop_config.json` (no Windows):

```json
{
  "mcpServers": {
    "worklog": {
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
        "JIRA_BASE_URL": "https://sua-empresa.atlassian.net",
        "JIRA_EMAIL": "voce@example.com",
        "JIRA_API_TOKEN": "seu-token"
      }
    }
  }
}
```

Alternativamente, use arquivo `.env` na raiz do repositório em vez de passar credenciais via ambiente.

### Fluxo Da Planilha

O agente traduz o bloco colado da planilha em chamadas de tools. O servidor apenas expõe as primitivas.

1. Usa a data de referência que você informar. Se não informar, o agente deve perguntar.
2. Classifica cada linha:
   - Começa com chave de tarefa, como `PROJ-123`: lança na tarefa.
   - Não tem chave: acha a tarefa antes com `search_tasks`, ou pula e mostra no preview.
3. Mostra preview com tarefa, duração, início e comentário.
4. Depois da confirmação, chama `log_work_batch`. Lançamentos já existentes no mesmo dia/horário são pulados e devolvidos em `skipped_duplicates`; você decide por linha se quer lançar mesmo assim via `log_work`.

**Nota:** Recursos específicos do provedor como `issue_key="daily"` do Jira são manipulados automaticamente pelo servidor.

### Variáveis De Ambiente

#### Seleção De Provedor

| Variável | Padrão | Descrição |
|---|---|---|
| `WORK_PROVIDER` | `jira` | Provedor ativo: `jira`, `redmine`, `github` ou `artia`. |

#### Jira Cloud (quando `WORK_PROVIDER=jira`)

| Variável | Obrigatória | Descrição |
|---|---|---|
| `JIRA_BASE_URL` | sim | URL do Jira Cloud, precisa ser HTTPS e um host `*.atlassian.net`, por exemplo `https://sua-empresa.atlassian.net`. |
| `JIRA_EMAIL` | sim | Email da conta Atlassian. |
| `JIRA_API_TOKEN` | sim | API token do Jira. |
| `JIRA_DAILY_JQL` | não | JQL que resolve `issue_key="daily"` para a tarefa-balde mensal. Use `{month}` (nome do mês em PT) e `{year}`, preenchidos pela data do worklog, ex. `project = MYPROJ AND summary ~ "Timesheet {month} de {year}" ORDER BY created DESC`. Vazio desliga o recurso. |

#### Redmine (quando `WORK_PROVIDER=redmine`)

| Variável | Obrigatória | Descrição |
|---|---|---|
| `REDMINE_URL` | sim | URL base do Redmine, ex. `https://redmine.example.com`. |
| `REDMINE_API_KEY` | sim | Chave API do Redmine. |

#### GitHub (quando `WORK_PROVIDER=github`)

| Variável | Obrigatória | Descrição |
|---|---|---|
| `GITHUB_TOKEN` | sim | Token de acesso pessoal (PAT) do GitHub. |

#### Artia (quando `WORK_PROVIDER=artia`)

| Variável | Obrigatória | Descrição |
|---|---|---|
| `ARTIA_API_URL` | não | URL GraphQL do Artia. Padrão: `https://api.artia.com/graphql`. |
| `ARTIA_CLIENT_ID` | sim | ClientId da integração Artia. |
| `ARTIA_SECRET` | sim | Secret da integração Artia. |
| `ARTIA_ACCOUNT_ID` | sim | ID da conta/workspace usado em get_task/worklogs. |
| `ARTIA_FOLDER_ID` | não | ID da pasta padrão para `search_tasks`. |
| `ARTIA_WORKLOG_STATUS_ID` | não | ID de status opcional enviado ao criar apontamento. |

As variáveis obrigatórias para seu provedor escolhido são lidas do `.env` (opcional) ou do ambiente do cliente MCP. Nenhum arquivo `.env` é obrigatório.

### Segurança

- **Menor privilégio:** o servidor é somente leitura/append. Não cria, edita, transiciona, atribui nem apaga tarefas, comentários ou worklogs. Nenhuma tool aponta para um endpoint destrutivo.
- **URLs dos provedores validadas:** Apenas HTTPS. URLs dos provedores (Jira, Redmine, etc.) são validadas.
- **Credenciais não ficam no código:** Vêm de variáveis de ambiente; `.env` é opcional e ignorado pelo Git.
- **Um único `httpx.Client` compartilhado** com pool, timeout fixo e limites de conexão por instância de provedor.
- **Caminhos locais da máquina** devem ficar em variáveis como `UV_PATH` e `MCP_PROJECT_DIR`.
- **Transporte stdio local:** não abre porta de rede.

### Desenvolvimento

```powershell
uv run pytest -q
```

Os testes usam [`respx`](https://lundberg.github.io/respx/) para mockar chamadas HTTP em vários provedores. Eles não chamam APIs reais.

Estrutura:

```text
worklog-mcp/
  pyproject.toml
  .env.example
  server.py                      # launcher fino -> src/server.py
  src/
    server.py                    # app FastMCP, registra as tools
    config.py                    # carrega .env, seleciona o provedor
    jira_client.py               # cliente HTTP da REST v3 do Jira
    redmine_client.py            # cliente API do Redmine
    github_client.py             # cliente REST API do GitHub
    artia_client.py              # cliente API do Artia
    utils.py
    models/                      # Task, Comment, Worklog, ProviderCapabilities
    providers/
      base.py                    # protocolo TaskProvider e BaseProvider
      jira_provider.py           # provedor Jira Cloud
      redmine_provider.py        # provedor Redmine
      github_provider.py         # provedor GitHub
      artia_provider.py          # provedor Artia
    services/
      provider_registry.py       # instâncias de provedores lazy-loaded
    tools/                       # um módulo por tool MCP
  tests/
```

### Arquitetura

- **Interface de provedor** (`src/providers/base.py`): protocolo `TaskProvider` define o contrato. Cada provedor implementa métodos obrigatórios (`whoami`, `search_tasks`, `get_task`) e opcionais controlados por `capabilities` (`add_comment`, `log_work`, `get_worklogs`).
- **Registry de provedor** (`src/services/provider_registry.py`): instancia e cacheia preguiçosamente os provedores baseado na variável `WORK_PROVIDER`.
- **Tools** (`src/tools/`): Sete tools FastMCP que chamam o provedor ativo através do registry.

### Troubleshooting

**O cliente MCP mostra o servidor como failed.**

Rode `uv run server.py` no repositório e veja o erro. Causas comuns: variáveis de ambiente ausentes, `uv` indisponível para o launcher ou `MCP_PROJECT_DIR` incorreto.

**Autenticação falha com erro de credenciais inválidas.**

Confira que você está usando o provedor correto e que as credenciais são válidas:
- Para Jira: `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`.
- Para Redmine: `REDMINE_URL`, `REDMINE_API_KEY`.
- Para GitHub: `GITHUB_TOKEN`.
- Para Artia: `ARTIA_CLIENT_ID`, `ARTIA_SECRET`, `ARTIA_ACCOUNT_ID`.

Gere um token novo se necessário.

**Worklog foi lançada em um provedor mas eu esperava outro.**

Confira a variável de ambiente `WORK_PROVIDER`. O padrão é `jira`. Configure explicitamente se necessário.

**A hora foi lançada mas não aparece no timesheet da empresa.**

Sua empresa pode usar um app separado (ex. Tempo Timesheets para Jira, etc.). Este servidor grava worklogs nativos do provedor.
