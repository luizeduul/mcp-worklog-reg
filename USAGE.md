# jira-worklog-mcp — guia de uso (para outra sessão)

Referência rápida do servidor MCP que **lança e confere horas (worklog) no Jira Cloud**
a partir de um agente (Claude Code, Cursor, etc.). Tudo genérico — substitua os
placeholders e use variáveis de ambiente; **nada de caminho de máquina ou nome de
instância chumbado**.

---

## 1. Pré-requisitos

- **uv** instalado (gerencia Python + roda o server). Instale:
  `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- Conta **Jira Cloud** com permissão de lançar horas.
- **Token CLÁSSICO** (sem scopes). Em `id.atlassian.com/manage-profile/security/api-tokens`
  use **"Create API token"**, NÃO o "with scopes".
  > Tokens *with scopes* não enxergam projetos **team-managed (Jira Software)** —
  > autenticam mas `/project` volta vazio e `BROWSE_PROJECTS=false`. Token clássico vê tudo.

## 2. Variáveis de ambiente

Lidas de um `.env` ao lado do `server.py` **ou** passadas pelo cliente MCP via `-e`.

| Variável | Obrig. | Descrição |
|---|---|---|
| `JIRA_BASE_URL` | sim | `https://<sua-instancia>.atlassian.net` (HTTPS e host `*.atlassian.net`) |
| `JIRA_EMAIL` | sim | e-mail da conta Atlassian |
| `JIRA_API_TOKEN` | sim | **token clássico** |
| `JIRA_DAILY_JQL` | não | JQL que resolve `issue_key="daily"` para a tarefa-balde mensal. `{month}` = mês PT, `{year}` = ano (da data do worklog). Vazio = recurso desligado. |

`.env` é **opcional** — o server funciona só com as variáveis vindas do cliente MCP.

## 3. Registrar no Claude Code (outra máquina/sessão)

```powershell
claude mcp add jira-worklog --scope user `
  -- "<CAMINHO_DO_UV>" --directory "<CAMINHO_DO_REPO>" run server.py
```

- `<CAMINHO_DO_UV>`: de preferência o **absoluto** (ex. `%USERPROFILE%\.local\bin\uv.exe`).
  Com `uv` "pelado" o health check pode dar **"Failed to connect"** se `~/.local/bin`
  não estiver no PATH do launcher.
- `<CAMINHO_DO_REPO>`: pasta onde está o `server.py` (use barra `/` mesmo no Windows).
- Com `.env` preenchido, **não precisa** `-e`. Recarregue a sessão e veja em `/mcp`.

Outros clientes (Cursor/Desktop) usam a mesma assinatura, muda só o arquivo de config.

---

## 4. Tools (7)

Servidor **somente leitura/append** (menor privilégio): não cria, edita, transiciona,
atribui nem apaga issues, comentários ou worklogs.

| Tool | Para que | Args principais |
|---|---|---|
| `jira_whoami` | valida auth; retorna `accountId`/`displayName` (token clássico) | — |
| `jira_search_issues` | acha issues | `query` (texto livre) ou `jql` (cru); sem args = minhas abertas; `max_results` |
| `jira_get_issue` | visão compacta de 1 issue | `issue_key` |
| `jira_add_comment` | adiciona comentário | `issue_key`, `comment` |
| `jira_log_work` | lança **1** worklog | `issue_key` (ou `"daily"`), `time_spent`, `started?`, `comment?` |
| `jira_log_work_batch` | lança **N** worklogs; pula duplicados no mesmo horário; reporta linha a linha | `entries`: lista de `{issue_key, time_spent, started?, comment?}` (`issue_key` pode ser `"daily"`); `skip_duplicates?` (default `true`) |
| `jira_get_worklogs` | lista worklogs de uma issue | `issue_key`, `mine_only?` |

**Formatos:**
- `time_spent`: `2:40` (H:MM) **ou** `1h 30m` / `45m` / `2h`.
- `started`: `YYYY-MM-DD` ou `YYYY-MM-DD HH:MM` (vazio = agora). Usa o fuso da máquina.
- `comment`: texto simples (o server converte pra ADF).
- `issue_key="daily"` (ou `"dayli"`): o server acha sozinho a tarefa-balde do mês via
  `JIRA_DAILY_JQL` (preenchendo mês/ano da data do lançamento) e lança lá — sem chutar
  ticket. Exige `JIRA_DAILY_JQL` configurada; senão retorna erro. A resposta traz
  `resolved_from: "daily"` e o `issue_key` real resolvido.

---

## 5. Como pedir (linguagem natural)

O **agente** traduz seu pedido nas tools — o server só expõe as primitivas.

**Lançar avulso:**
> "lança 1h30 na PROJ-123, comentário 'ajuste X', hoje"
> → `jira_log_work(issue_key="PROJ-123", time_spent="1h 30m", comment="ajuste X")`

**Conferir:**
> "mostra os worklogs da PROJ-123 (só os meus)"
> → `jira_get_worklogs(issue_key="PROJ-123", mine_only=true)`

**Comentar:**
> "comenta 'subi o fix' na PROJ-123"
> → `jira_add_comment(issue_key="PROJ-123", comment="subi o fix")`

**Em lote (planilha):** cole o bloco e **informe a data de referência**. O agente:
1. Usa a data que você passar (não chuta).
2. Classifica cada linha:
   - começa com `^[A-Z]+-\d+` (ex. `PROJ-123`) → vira a issue; o resto do texto vira o comentário;
   - linha de **daily** → `issue_key="daily"` (o server resolve a tarefa-balde do mês, sem perguntar);
   - sem código → acha a issue antes com `jira_search_issues`, ou **não lança** e lista como pulada.
3. Mostra **preview** (`código | duração | início | comentário`) e pede OK.
4. Lança via `jira_log_work_batch`. Linhas já existentes no mesmo dia/horário voltam em
   `skipped_duplicates` — o agente pergunta o que fazer com elas (lançar mesmo assim via
   `jira_log_work` ou deixar como está).

---

## 6. Gotchas

- **Token clássico obrigatório** nesta família de instâncias (scoped não vê team-managed).
- **Worklog nativo do Jira** — se a empresa usa **Tempo Timesheets**, o lançamento pode
  não aparecer no timesheet do Tempo (confira com `jira_get_worklogs`).
- **`currentUser()`**: funciona com token clássico (resolve identidade). Com scoped, não.
- **Caminho do `uv`**: use absoluto se o health check falhar por PATH.
- `.env` é **gitignorado** — nunca versione o token.

---

## 7. Teste rápido de auth

```powershell
"<CAMINHO_DO_UV>" --directory "<CAMINHO_DO_REPO>" run python -c "import server; print(server.jira_whoami())"
```
Esperado: `{'ok': True, 'accountId': ..., 'displayName': ...}`.
