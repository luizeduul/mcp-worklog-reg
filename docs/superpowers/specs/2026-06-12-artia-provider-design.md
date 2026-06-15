# ArtiaProvider — Design (Work MCP, Fase 3)

Data: 2026-06-12 · Branch: `feature/mcp-worklog`

## Objetivo

Integrar o Artia à abstração `TaskProvider` do Work MCP, seguindo a mesma
filosofia dos providers existentes (Jira, Redmine, GitHub): menor privilégio,
poucas operações, nada destrutivo, respostas pequenas para LLMs, tipagem forte,
alta cobertura de testes.

## Diferença estrutural: GraphQL

Ao contrário de Jira/Redmine/GitHub (REST), o Artia expõe **uma única
endpoint GraphQL**: `https://api.artia.com/graphql`. Todas as operações são
`POST` com `{ query, variables }`. Erros podem chegar como **HTTP 200 com um
array `errors[]` no corpo** — o cliente precisa tratar isso além dos status HTTP.

Fonte: Postman collection oficial do Artia (developers.artia.com →
documenter.getpostman.com/view/10208526/TVCZaWK4).

## Autenticação (2 etapas)

1. Mutation `authenticationByClient(clientId, secret) { token }` → devolve um token.
2. Token vai como `Authorization: Bearer <token>` nas chamadas seguintes.

- Credencial = **ClientId + Secret** (gerados em Configurar Organização →
  Integrações → Gerar API keys). Credencial de serviço, não pessoal.
- Token cacheado em memória (lazy). Reautentica **uma vez** ao receber 401 /
  token expirado; se falhar de novo, propaga `ArtiaError`.

## Escopo / identidade

O Artia escopa quase tudo por `accountId` (workspace/organização) e a listagem
de atividades exige `folderId`. **Não existe busca global "minhas tarefas"** como
em Jira/GitHub. Consequência:

- `ARTIA_ACCOUNT_ID` (obrigatório) — usado em get_activity e apontamentos.
- `ARTIA_FOLDER_ID` (opcional) — folder default do `search_tasks` (análogo a
  `GITHUB_REPO`). Sem ele e sem argumento, `search_tasks` devolve erro claro.

## Capacidades reais (ProviderCapabilities)

| Recurso        | Status inicial | Observação |
|----------------|----------------|------------|
| comments       | **False**      | Não há mutation de criar comentário confirmada na collection (`comments` só aparece como campo de leitura da atividade). Reavaliar na Fase C. |
| worklogs       | **True** (Fase B) | Apontamentos: `Listar` (get) + `Criar` (log). Na Fase A fica `False` até estar implementado e validado. |

Princípio: adaptar-se às capacidades reais do Artia — nunca forçar interface
incompatível. Capability só vira `True` quando o método correspondente existe e
foi testado.

## Componentes

### `src/errors.py`
Adicionar `class ArtiaError(ProviderError)` (junto de JiraError/RedmineError/GitHubError).

### `src/artia_client.py` (novo)
Cliente GraphQL read/append-only. Espelha a estrutura de `redmine_client.py`/
`github_client.py`:

- Pool `httpx.Client` compartilhado no módulo + fechamento via `atexit`.
- `_DEFAULT_API = "https://api.artia.com/graphql"`.
- `_validate_base_url`: exige http/https + hostname; remove barra final.
- `__init__(client_id, secret, base_url=_DEFAULT_API, timeout=30.0)` →
  `ArtiaError` se faltar client_id/secret.
- `from_env()` → lê `ARTIA_CLIENT_ID`, `ARTIA_SECRET`, `ARTIA_API_URL` (default
  api.artia.com).
- `_authenticate()` → roda `authenticationByClient`, guarda `self._token`.
- `_post(query, variables, *, retries=3)` → injeta Bearer; **retry com
  exponential backoff** (0.5/1/2s) em 429, 5xx e falha de rede; reautentica 1x
  em 401; levanta `ArtiaError` com mensagem amigável (`_map_error`); valida
  `errors[]` do corpo GraphQL (`_check_graphql_errors`).
- `_extract_detail`: lê `message`/`errors[].message` do JSON sem vazar payload cru.
- Métodos read/append apenas:
  - `account()` → query do account/usuário corrente (para whoami). Se a API não
    tiver query de "me", whoami usa `ARTIA_ACCOUNT_ID` + validação de token.
  - `list_activities(folder_id, limit, ...)` → query "Listar Atividades".
  - `get_activity(account_id, activity_id)` → query "Visualizar Atividade".
  - `list_time_entries(account_id, activity_id)` → query "Listar" apontamentos. *(Fase B)*
  - `create_time_entry(account_id, activity_id, date_at, start_time, duration, status_id)` → mutation "Criar". *(Fase B)*

**Proibido no cliente:** nenhuma mutation de criar/editar/excluir atividade,
mudar situação/status, atribuir responsável, editar/remover apontamento,
criar dependências. Esses métodos simplesmente não existem.

### `src/providers/artia_provider.py` (novo)
`ArtiaProvider(BaseProvider)`:

- `__init__(client, account_id, folder_id="")`.
- `from_env()` → `cls(ArtiaClient.from_env(), os.getenv("ARTIA_ACCOUNT_ID","").strip(), os.getenv("ARTIA_FOLDER_ID","").strip())`.
- `name` → `"artia"`.
- `capabilities` → `ProviderCapabilities(supports_comments=False, supports_worklogs=<False na A / True na B>)`.
- `whoami()` → `{provider:"artia", ok:True, accountId, displayName}`.
- `search_tasks(query="", native_query="", max_results=...)`:
  - folder = native_query (override) ou `folder_id` default; sem folder → `ArtiaError`.
  - chama `list_activities`; mapeia → `Task(id=str(id), summary=title, status, url)`.
  - filtra responsável=eu quando a API permitir; senão devolve o folder inteiro.
- `get_task(task_id)` → `get_activity(account_id, task_id)`; mapeia título,
  description, responsible→assignee, situação→status, categorias→labels, url.
- `log_work(...)` / `get_worklogs(...)` → Fase B (mapeiam para/de apontamentos;
  convertem segundos ↔ unidade de `duration` do Artia depois de validada;
  `started` → `dateAt` (data) + `startTime` (hora)). Até lá, herdam o
  `NotImplementedError` do BaseProvider.
- `add_comment(...)` → só na Fase C, se houver mutation. Senão não existe.
- `group_entries` → default (identidade), salvo necessidade comprovada.

Mapeamento Artia → modelos padronizados (`Task`/`Comment`/`Worklog`): expõe só os
campos canônicos; nada de devolver o objeto cru do Artia para a IA.

### Registro
- `src/services/provider_registry.py` → `registry.register("artia", ArtiaProvider.from_env)`.
- `src/providers/__init__.py` → importa/exporta `ArtiaProvider`.
- `.env.example` → seção Artia (comentada): `WORK_PROVIDER`, `ARTIA_CLIENT_ID`,
  `ARTIA_SECRET`, `ARTIA_ACCOUNT_ID`, `ARTIA_FOLDER_ID`, `ARTIA_API_URL`, nota
  sobre comments/worklogs.

## Faseamento de implementação

- **Fase A (esta entrega):** errors + artia_client (auth + account + list +
  get) + artia_provider (whoami/search_tasks/get_task) + registro + env +
  testes. `capabilities(comments=False, worklogs=False)`.
- **Fase B:** apontamentos — `list_time_entries`/`create_time_entry` no cliente;
  `get_worklogs`/`log_work` no provider; validar unidade de `duration`; flip
  `supports_worklogs=True`. Testes adicionais.
- **Fase C:** investigar mutation de comentário. Se existir, `add_comment` +
  `supports_comments=True`; senão, documentar como não suportado e parar.

## Testes

- `tests/test_artia_client.py` — respx mockando o `POST /graphql`, com
  `side_effect` roteando pelo nome da operação no corpo (auth vs listar vs
  visualizar). Cobre: exige credenciais, rejeita scheme não-http, fluxo de
  token (auth → Bearer), tratamento de `errors[]` GraphQL, mapeamento de 401,
  reautenticação, retry/backoff, falha de rede embrulhada.
- `tests/providers/test_artia_provider.py` — whoami, search default (folder),
  search sem folder → erro, mapeamento de `get_task`, capabilities
  (comments/worklogs conforme a fase). Fase B acrescenta log_work/get_worklogs.

## Não-objetivos

- Editar/excluir/transicionar atividades; atribuir responsáveis; criar tarefas;
  editar/remover apontamentos; dependências; campos customizados de escrita.
- Renomear as 7 tools MCP (`jira_*` permanecem).

## Riscos / incertezas a resolver na implementação

1. Existência e shape de uma query "account/me" para o `whoami`.
2. Unidade exata de `duration` no apontamento (segundos? minutos? decimal de horas?).
3. Filtro de "atribuído a mim" no `list_activities` (campo `responsible`).
4. Existência de mutation de comentário (define a capability de comments).
5. Confirmar base URL: `api.artia.com/graphql` (collection) vs `app.artia.com/graphql` (KB).
