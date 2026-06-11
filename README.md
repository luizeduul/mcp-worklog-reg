# jira-worklog-mcp

Servidor [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) que permite **lançar e conferir horas (worklog) no Jira Cloud** direto de um agente de IA — Claude Code, Claude Desktop, Cursor, e qualquer cliente MCP que fale stdio.

Pensado para um fluxo real: você cola um bloco da sua planilha de horas (código da tarefa, início, fim, comentário) e o agente lança cada linha na issue certa do Jira, com o comentário no worklog.

---

## Sumário

- [Como funciona](#como-funciona)
- [Tools expostas](#tools-expostas)
- [Pré-requisitos](#pré-requisitos)
- [Instalação](#instalação)
  - [1. Clonar e configurar o `.env`](#1-clonar-e-configurar-o-env)
  - [2. Gerar o token do Jira](#2-gerar-o-token-do-jira)
  - [3. Instalar dependências](#3-instalar-dependências)
  - [4. Testar standalone](#4-testar-standalone)
  - [5. Registrar em um cliente MCP](#5-registrar-em-um-cliente-mcp)
- [Fluxo: lançar a partir da planilha](#fluxo-lançar-a-partir-da-planilha)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Segurança](#segurança)
- [Desenvolvimento](#desenvolvimento)
- [Troubleshooting](#troubleshooting)

---

## Como funciona

```
┌──────────────────┐   stdio (JSON-RPC)   ┌──────────────────┐   HTTPS    ┌────────────┐
│  Cliente MCP     │ ───────────────────► │ jira-worklog-mcp │ ─────────► │ Jira Cloud │
│  (Claude Code,   │ ◄─────────────────── │   (Python)       │ ◄───────── │  REST v3   │
│   Cursor, etc.)  │                      │                  │            │            │
└──────────────────┘                      └──────────────────┘            └────────────┘
```

- **Transport: stdio.** O cliente MCP inicia o `server.py` como subprocesso e fala por `stdin`/`stdout`. Sem servidor HTTP, sem porta aberta.
- **Auth:** Basic auth (`email:api_token` em Base64) contra a REST v3 do Jira Cloud. As credenciais vêm **só de variáveis de ambiente** — nada é chumbado no código.
- **Duas camadas:** `jira_client.py` (HTTP puro, não sabe de MCP) e `server.py` (FastMCP — converte input humano e expõe as tools).

---

## Tools expostas

| Tool | O que faz |
|---|---|
| `jira_whoami` | Valida a autenticação. Retorna sua identidade com token clássico; com token **scoped** confirma a conexão via busca (o Jira não expõe `/myself` a tokens com scopes — ver nota abaixo). |
| `jira_search_issues` | Acha issues: sem args = minhas abertas; `query` = texto livre; `jql` = JQL cru. |
| `jira_log_work` | Lança **1** worklog. `time_spent` aceita `2:40` (H:MM) ou `1h 30m`. |
| `jira_log_work_batch` | Lança **N** worklogs de uma vez (fluxo da planilha). Reporta sucesso/falha por linha. |
| `jira_get_worklogs` | Lista os worklogs de uma issue. `mine_only` filtra os seus. |
| `jira_delete_worklog` | Apaga um worklog. Requer o scope `delete:issue-worklog:jira` no token. |

---

## Pré-requisitos

- **[uv](https://github.com/astral-sh/uv)** (recomendado) — gerencia Python e dependências. Instale com:
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
  O `uv` baixa o Python 3.12 automaticamente (`uv python install 3.12`). Não precisa de Python instalado no sistema.
- Uma conta no **Jira Cloud** com permissão de lançar horas nas issues.

---

## Instalação

### 1. Clonar e configurar o `.env`

```powershell
git clone <url-do-repo> jira-worklog-mcp
cd jira-worklog-mcp
cp .env.example .env
```

Edite o `.env` com sua URL, email e token (próximo passo). **O `.env` é gitignorado — nunca o versione.**

### 2. Gerar o token do Jira

Use um **API token CLÁSSICO** (sem scopes):

1. Acesse https://id.atlassian.com/manage-profile/security/api-tokens
2. Clique em **"Create API token"** (o de cima, **sem** scopes — NÃO o "Create API token with scopes").
3. Dê um nome, copie o token (ele só aparece uma vez) e cole em `JIRA_API_TOKEN` no `.env`.

> **Por que clássico e não "with scopes":** nesta instância (`gredom.atlassian.net`), os
> **tokens com scopes não enxergam projetos team-managed (Jira Software)** — eles autenticam,
> mas `/project` volta vazio e `BROWSE_PROJECTS` fica `false`, então não acham issue nenhuma.
> Testado: scoped (8 e 9 scopes) → 0 projetos; **clássico → 27 projetos**, vê GAZIN/GREDOM.
> O token clássico herda **todas** as permissões da sua conta; o que limita o agente é o
> **conjunto de tools** que este server expõe (só worklog + busca).

### 3. Instalar dependências

```powershell
uv sync
```

Cria o `.venv` e instala tudo (resolve em segundos).

### 4. Testar standalone

```powershell
uv run server.py
```

Fica em foreground escutando MCP via stdio (Ctrl+C encerra). Em uso normal o cliente MCP cuida disso — esse passo serve só para confirmar que sobe sem erro.

Para um teste rápido de auth:

```powershell
uv run python -c "import server; print(server.jira_whoami())"
```

Deve imprimir `ok: true` com `accountId`/`displayName` (token clássico). Se vier `{'erro': ...}`, revise token/email/URL.

> **`/myself` e token:** com **token clássico** (recomendado aqui), `/rest/api/3/myself` funciona e o `jira_whoami` retorna `accountId`/`displayName`. Tokens **com scopes** dão 401 em `/myself` e, pior, **não veem projetos team-managed** (ver passo 2) — por isso não são usados nesta instância.

### 5. Registrar em um cliente MCP

Substitua o caminho pelo absoluto onde você clonou o repo.

#### Claude Code

Scope `user` deixa disponível em todos os seus projetos. Com o `.env` já preenchido, **não precisa** passar `-e`:

```powershell
claude mcp add jira-worklog --scope user `
  -- C:/Users/GREDOM3/.local/bin/uv.exe --directory "C:/Projetos/MCP/jira-worklog-mcp" run server.py
```

> Use o **caminho absoluto** do `uv`. Com `uv` "pelado", o health check do `claude mcp get`
> pode dar **"Failed to connect"** quando o `~/.local/bin` não está no PATH do launcher.

Se preferir passar as credenciais no registro em vez do `.env`:

```powershell
claude mcp add jira-worklog --scope user `
  -e JIRA_BASE_URL=https://SUAEMPRESA.atlassian.net `
  -e JIRA_EMAIL=voce@empresa.com `
  -e JIRA_API_TOKEN=SEU_TOKEN `
  -- C:/Users/GREDOM3/.local/bin/uv.exe --directory "C:/Projetos/MCP/jira-worklog-mcp" run server.py
```

Reinicie a sessão e confirme com `/mcp`.

#### Claude Desktop / Cursor / outros

Qualquer cliente MCP via stdio usa a mesma assinatura — muda só onde fica o arquivo de config:

```json
{
  "mcpServers": {
    "jira-worklog": {
      "command": "uv",
      "args": ["--directory", "C:/Projetos/MCP/jira-worklog-mcp", "run", "server.py"]
    }
  }
}
```

Com `.env` preenchido, as credenciais são lidas dele. (Claude Desktop: `%APPDATA%\Claude\claude_desktop_config.json`. Cursor: `~/.cursor/mcp.json`.)

---

## Fluxo: lançar a partir da planilha

A tradução do bloco da planilha → chamadas das tools é feita pelo **agente** (o server só expõe as primitivas). Cole o bloco e informe a data de referência. O agente:

1. **Usa a data que você passar.** Se você não passar, ele pergunta — não chuta do cabeçalho nem de hoje.
2. **Classifica cada linha:**
   - Começa com código `^[A-Z]+-\d+` (ex. `ROTA-355`, `GAZIN-753`) → vira a issue; o resto do texto vira o comentário do worklog.
   - É `daily` → resolve a tarefa mensal no projeto `JIRA_DAILY_PROJECT` buscando `<seu nome> <mês> <ano>`.
   - Sem código e não-daily → **não lança**; só lista como pulada.
3. **Mostra um preview** (`código | duração | início | comentário` + as puladas) e pede OK.
4. **Lança** via `jira_log_work_batch` e **reporta** linha a linha (id ou erro) + total.

A duração usa a coluna **Duração** (`2:40` → 2h40m) e o horário usa a data de referência + a coluna **Início**.

---

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `JIRA_BASE_URL` | sim | URL do Jira Cloud, ex. `https://empresa.atlassian.net`. |
| `JIRA_EMAIL` | sim | Email da conta Atlassian. |
| `JIRA_API_TOKEN` | sim | API token granular (ver scopes acima). |
| `JIRA_DAILY_PROJECT` | não | Projeto da tarefa mensal do daily (default `GREDOM`). |

Lidas de um `.env` ao lado do `server.py` **ou** passadas pelo cliente MCP via `-e`. Faltando qualquer uma das obrigatórias, a chamada retorna um erro claro.

---

## Segurança

- **Sem credenciais no código.** Tudo vem de variáveis de ambiente (`.env` ou `-e`). O `.gitignore` já cobre o `.env`.
- **Transport stdio local.** Sem porta, sem rede de entrada. Quem não tem acesso ao seu shell não invoca nada.
- **Token clássico = acesso total da conta.** O que limita o agente é o **conjunto de tools** deste server (só worklog + busca): ele não cria/edita issue nem muda status porque não existe tool pra isso. (Tokens "with scopes" seriam mais restritos no token, mas não funcionam nesta instância — ver Instalação, passo 2.)
- **Antes de publicar:** confirme que o `.env` não foi commitado (`git status` deve ignorá-lo).

---

## Desenvolvimento

```powershell
uv run pytest -q
```

Os testes usam [`respx`](https://lundberg.github.io/respx/) para mockar o HTTP do Jira — **não batem na API real** e não precisam de token. Estrutura:

```
jira-worklog-mcp/
  pyproject.toml          # deps + config do pytest
  .env.example            # template das variáveis
  server.py               # FastMCP: conversão de input + 6 tools
  jira_client.py          # HTTP puro (httpx): auth, REST v3, erros
  tests/
    test_jira_client.py   # client (auth, endpoints, mapeamento de erro)
    test_server.py        # helpers de conversão + tools
```

---

## Troubleshooting

**`/mcp` mostra o servidor como `failed` no Claude Code.**
Rode `uv run server.py` no terminal e veja o erro. Causas comuns: `.env` ausente/incompleto, `uv` fora do PATH, ou caminho do `--directory` errado (use barra normal `/` mesmo no Windows).

**`jira_whoami` retorna `{'erro': 'Token inválido ou expirado...'}`.**
Token errado/expirado, ou `JIRA_EMAIL`/`JIRA_BASE_URL` incorretos. Gere um novo token e confira a URL.

**`{'erro': 'Sem permissão. Confira os scopes do token.'}`.**
Falta um scope. Para lançar horas você precisa de `write:issue-worklog:jira`; para apagar, `delete:issue-worklog:jira`.

**Lancei a hora mas ela não aparece no meu timesheet.**
Sua empresa provavelmente usa o plugin **Tempo Timesheets**, que tem worklog próprio. Este server usa o worklog **nativo** do Jira. Confirme com `jira_get_worklogs` (se aparecer lá, foi lançado no nativo). Suporte ao Tempo está fora do escopo atual.
