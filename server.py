"""
MCP server para lançar e conferir horas (worklog) no Jira Cloud.

Tools:
- jira_whoami:           confirma auth, retorna usuário atual.
- jira_search_issues:    acha issue keys (minhas abertas / texto livre / JQL).
- jira_log_work:         lança 1 worklog.
- jira_log_work_batch:   lança N worklogs (fluxo da planilha), reporta por linha.
- jira_get_worklogs:     lista worklogs de uma issue.
- jira_delete_worklog:   apaga um worklog (requer scope delete:issue-worklog:jira).

Config (env, lidas do .env ao lado deste arquivo ou passadas pelo cliente MCP):
JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_DAILY_PROJECT (opcional, default GREDOM).
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from jira_client import JiraClient, JiraError

# Carrega .env ao lado deste arquivo, independente do CWD do cliente MCP.
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

mcp = FastMCP("JiraWorklogMCP", log_level="ERROR")

_HHMM_RE = re.compile(r"^(\d+):([0-5]\d)$")
_JIRA_DUR_RE = re.compile(r"(\d+)\s*([hm])")


# ---------------------------------------------------------------------------
# Helpers de conversão (puros — testáveis sem rede)
# ---------------------------------------------------------------------------


def parse_time_spent(value: str) -> int:
    """Converte '2:40' (H:MM) ou '1h 30m' / '45m' / '2h' em segundos."""
    value = (value or "").strip()
    m = _HHMM_RE.match(value)
    if m:
        secs = (int(m.group(1)) * 60 + int(m.group(2))) * 60
    else:
        total = 0
        achou = False
        for num, unit in _JIRA_DUR_RE.findall(value.lower()):
            achou = True
            total += int(num) * (3600 if unit == "h" else 60)
        if not achou:
            raise ValueError(
                f"Tempo inválido: '{value}'. Use 'H:MM' (ex. '2:40') ou '1h 30m'."
            )
        secs = total
    if secs <= 0:
        raise ValueError("Tempo deve ser maior que zero.")
    return secs


def to_jira_datetime(value: str) -> str:
    """
    Converte 'AAAA-MM-DD' ou 'AAAA-MM-DD HH:MM[:SS]' no formato do Jira
    (yyyy-MM-ddTHH:mm:ss.SSSZ com offset local, ex. ...-0300).
    """
    value = (value or "").strip()
    dt = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        raise ValueError(
            f"Data/hora inválida: '{value}'. Use 'AAAA-MM-DD' ou 'AAAA-MM-DD HH:MM'."
        )
    local = dt.astimezone()  # naive → assume fuso local da máquina
    millis = f"{local.microsecond // 1000:03d}"
    return local.strftime("%Y-%m-%dT%H:%M:%S.") + millis + local.strftime("%z")


def build_adf_comment(text: str) -> dict[str, Any]:
    """Monta um comentário ADF (Atlassian Document Format) de um parágrafo."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        ],
    }


def _adf_to_text(adf: Any) -> str:
    """Extrai texto plano de um comentário ADF (best-effort)."""
    if not isinstance(adf, dict):
        return ""
    partes: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "text" and isinstance(node.get("text"), str):
                partes.append(node["text"])
            for child in node.get("content", []) or []:
                walk(child)

    walk(adf)
    return " ".join(partes).strip()


def _erro(e: Exception) -> dict[str, Any]:
    """Formata exceção como saída estruturada (nunca stacktrace cru)."""
    if isinstance(e, JiraError):
        out: dict[str, Any] = {"erro": e.message}
        if e.detail:
            out["detalhe"] = e.detail
        return out
    return {"erro": str(e)}


def _client() -> JiraClient:
    """Instancia o client por chamada (lazy) — importar este módulo não exige env."""
    return JiraClient.from_env()


# ---------------------------------------------------------------------------
# Tools MCP
# ---------------------------------------------------------------------------


@mcp.tool(
    name="jira_whoami",
    description="Confirma que a autenticação no Jira funciona. Retorna a identidade quando o token permite.",
)
def jira_whoami() -> dict[str, Any]:
    """
    QUANDO USAR
    - Validar que JIRA_BASE_URL/EMAIL/API_TOKEN estão certos antes de lançar horas.

    SAIDA
    - {ok, accountId, displayName, emailAddress} quando a identidade é acessível
      (token clássico), OU {ok, identidade, nota} quando o token tem scopes e o
      Jira não expõe /myself (auth é validada por uma busca). {erro} em falha real.
    """
    try:
        client = _client()
        user = client.current_user()
        if user:
            return {
                "ok": True,
                "accountId": user.get("accountId"),
                "displayName": user.get("displayName"),
                "emailAddress": user.get("emailAddress"),
            }
        # Token com scopes não expõe identidade: confirma a auth com uma busca real.
        client.search_issues("assignee = currentUser() ORDER BY updated DESC", 1)
        return {
            "ok": True,
            "identidade": os.getenv("JIRA_EMAIL"),
            "nota": (
                "Token com scopes não acessa /myself; identidade vem da config "
                "(JIRA_EMAIL). Auth validada via busca."
            ),
        }
    except (JiraError, ValueError) as e:
        return _erro(e)


@mcp.tool(
    name="jira_search_issues",
    description=(
        "Acha issues do Jira. Sem args: minhas issues abertas. 'query': texto livre. "
        "'jql': JQL cru (avançado)."
    ),
)
def jira_search_issues(
    query: Annotated[str, Field(description="Texto livre. Vira: text ~ \"<query>\".")] = "",
    jql: Annotated[str, Field(description="JQL cru. Tem prioridade sobre query.")] = "",
    max_results: Annotated[int, Field(description="Máximo de issues retornadas.")] = 20,
) -> dict[str, Any]:
    """
    QUANDO USAR
    - Descobrir a key de uma issue antes de lançar hora.
    - Resolver a tarefa mensal do daily: jql='project = GREDOM AND summary ~ "Luiz junho 2026"'.

    SAIDA
    - jql (efetivo), count, issues: [{key, summary, status}]
    """
    try:
        if (jql or "").strip():
            final_jql = jql.strip()
        elif (query or "").strip():
            safe = query.strip().replace('"', '\\"')
            final_jql = f'text ~ "{safe}" ORDER BY updated DESC'
        else:
            final_jql = (
                "assignee = currentUser() AND statusCategory != Done "
                "ORDER BY updated DESC"
            )
        data = _client().search_issues(final_jql, max_results)
        issues = []
        for it in data.get("issues", []):
            fields = it.get("fields") or {}
            status = fields.get("status") or {}
            issues.append(
                {
                    "key": it.get("key"),
                    "summary": fields.get("summary"),
                    "status": status.get("name"),
                }
            )
        return {"jql": final_jql, "count": len(issues), "issues": issues}
    except (JiraError, ValueError) as e:
        return _erro(e)


def _resolver_started(started: str) -> str:
    """started informado → formato Jira; vazio → agora (fallback p/ log avulso)."""
    if (started or "").strip():
        return to_jira_datetime(started)
    return to_jira_datetime(datetime.now().strftime("%Y-%m-%d %H:%M"))


@mcp.tool(
    name="jira_log_work",
    description=(
        "Lança 1 worklog numa issue. time_spent aceita 'H:MM' (ex. '2:40') ou "
        "'1h 30m'. started: 'AAAA-MM-DD' ou 'AAAA-MM-DD HH:MM' (vazio = agora)."
    ),
)
def jira_log_work(
    issue_key: Annotated[str, Field(description="Key da issue, ex. ROTA-355, GAZIN-753.")],
    time_spent: Annotated[str, Field(description="Duração: 'H:MM' (2:40) ou '1h 30m'.")],
    started: Annotated[str, Field(description="Início: 'AAAA-MM-DD HH:MM'. Vazio = agora.")] = "",
    comment: Annotated[str, Field(description="Comentário do worklog (vai pra task).")] = "",
) -> dict[str, Any]:
    """
    QUANDO USAR
    - Lançar uma hora avulsa numa issue específica.

    SAIDA
    - id, issue_key, time_spent_seconds, started  (ou {erro, detalhe})
    """
    try:
        secs = parse_time_spent(time_spent)
        started_jira = _resolver_started(started)
        adf = build_adf_comment(comment) if (comment or "").strip() else None
        res = _client().log_work(issue_key, secs, started_jira, adf)
        return {
            "id": res.get("id"),
            "issue_key": issue_key,
            "time_spent_seconds": secs,
            "started": started_jira,
        }
    except (JiraError, ValueError) as e:
        return _erro(e)


@mcp.tool(
    name="jira_log_work_batch",
    description=(
        "Lança N worklogs numa chamada (fluxo da planilha). entries: lista de "
        "{issue_key, time_spent, started?, comment?}. Reporta sucesso/falha por linha."
    ),
)
def jira_log_work_batch(
    entries: Annotated[list[dict], Field(description="Lista de {issue_key, time_spent, started?, comment?}.")],
) -> dict[str, Any]:
    """
    QUANDO USAR
    - Lançar um dia inteiro da planilha de uma vez (depois do preview confirmado).

    SAIDA
    - total, ok, failed, results: [{issue_key, ok, id?, started?, error?}]
    """
    client = _client()
    results: list[dict[str, Any]] = []
    for entry in entries:
        key = entry.get("issue_key", "?")
        try:
            secs = parse_time_spent(entry["time_spent"])
            started_jira = _resolver_started(entry.get("started", ""))
            comment = entry.get("comment", "")
            adf = build_adf_comment(comment) if (comment or "").strip() else None
            res = client.log_work(entry["issue_key"], secs, started_jira, adf)
            results.append(
                {"issue_key": key, "ok": True, "id": res.get("id"), "started": started_jira}
            )
        except (JiraError, ValueError, KeyError) as e:
            results.append({"issue_key": key, "ok": False, "error": str(e)})
    ok = sum(1 for r in results if r["ok"])
    return {"total": len(results), "ok": ok, "failed": len(results) - ok, "results": results}


@mcp.tool(
    name="jira_get_worklogs",
    description="Lista os worklogs de uma issue. mine_only filtra os do usuário atual.",
)
def jira_get_worklogs(
    issue_key: Annotated[str, Field(description="Key da issue.")],
    mine_only: Annotated[bool, Field(description="Só os meus worklogs.")] = False,
) -> dict[str, Any]:
    """
    QUANDO USAR
    - Conferir o que foi lançado numa issue (validar o lançamento).

    SAIDA
    - count, worklogs: [{id, author, time_spent, started, comment}]
    """
    try:
        client = _client()
        data = client.get_worklogs(issue_key)
        me = None
        nota = None
        if mine_only:
            user = client.current_user()
            me = user.get("accountId") if user else None
            if me is None:
                nota = (
                    "mine_only ignorado: identidade indisponível para token com "
                    "scopes (/myself bloqueado)."
                )
        out = []
        for w in data.get("worklogs", []):
            author = w.get("author") or {}
            if mine_only and me is not None and author.get("accountId") != me:
                continue
            out.append(
                {
                    "id": w.get("id"),
                    "author": author.get("displayName"),
                    "time_spent": w.get("timeSpent"),
                    "started": w.get("started"),
                    "comment": _adf_to_text(w.get("comment")),
                }
            )
        res = {"issue_key": issue_key, "count": len(out), "worklogs": out}
        if nota:
            res["nota"] = nota
        return res
    except (JiraError, ValueError) as e:
        return _erro(e)


@mcp.tool(
    name="jira_delete_worklog",
    description=(
        "Apaga um worklog. Requer scope delete:issue-worklog:jira no token "
        "(senão retorna erro de permissão)."
    ),
)
def jira_delete_worklog(
    issue_key: Annotated[str, Field(description="Key da issue.")],
    worklog_id: Annotated[str, Field(description="ID do worklog (de jira_get_worklogs).")],
) -> dict[str, Any]:
    """
    QUANDO USAR
    - Desfazer um lançamento errado.

    SAIDA
    - deleted: <worklog_id>  (ou {erro, detalhe})
    """
    try:
        return _client().delete_worklog(issue_key, worklog_id)
    except (JiraError, ValueError) as e:
        return _erro(e)


if __name__ == "__main__":
    mcp.run(transport="stdio")
