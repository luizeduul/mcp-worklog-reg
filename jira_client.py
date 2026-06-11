"""Cliente HTTP do Jira Cloud REST v3. Não sabe nada de MCP."""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx

JIRA_API = "/rest/api/3"


class JiraError(Exception):
    """Erro tratado do Jira, com mensagem amigável para o usuário."""

    def __init__(self, message: str, status: int | None = None, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.detail = detail


class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str, timeout: float = 30.0):
        if not (base_url and email and api_token):
            raise JiraError(
                "JIRA_BASE_URL, JIRA_EMAIL e JIRA_API_TOKEN precisam estar definidos."
            )
        self.base_url = base_url.rstrip("/")
        self.email = email
        token = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        self._headers = {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._timeout = timeout

    @classmethod
    def from_env(cls) -> "JiraClient":
        return cls(
            base_url=os.getenv("JIRA_BASE_URL", ""),
            email=os.getenv("JIRA_EMAIL", ""),
            api_token=os.getenv("JIRA_API_TOKEN", ""),
        )

    # -- núcleo HTTP -------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = httpx.request(
                method,
                url,
                headers=self._headers,
                json=json_body,
                params=params,
                timeout=self._timeout,
            )
        except httpx.HTTPError as e:
            raise JiraError("Falha de rede ao acessar o Jira.", detail=str(e))
        if resp.status_code >= 400:
            raise self._map_error(resp)
        if resp.status_code == 204:
            return None
        if not resp.content:
            raise JiraError(
                f"Jira retornou resposta vazia com HTTP {resp.status_code}.",
                status=resp.status_code,
            )
        return resp.json()

    def _map_error(self, resp: httpx.Response) -> JiraError:
        status = resp.status_code
        detail = self._extract_detail(resp)
        if status == 401:
            msg = "Token inválido ou expirado. Gere um novo em id.atlassian.com."
        elif status == 403:
            msg = "Sem permissão. Confira os scopes do token."
        elif status == 404:
            msg = "Recurso não encontrado (issue inexistente ou sem acesso)."
        elif status == 400:
            msg = "Requisição inválida (cheque formato dos dados)."
        else:
            msg = f"Jira retornou HTTP {status}."
        return JiraError(msg, status=status, detail=detail)

    @staticmethod
    def _extract_detail(resp: httpx.Response) -> str:
        try:
            data = resp.json()
        except Exception:
            return resp.text[:300]
        if isinstance(data, dict):
            msgs = data.get("errorMessages") or []
            errs = data.get("errors") or {}
            partes = list(msgs) + [f"{k}: {v}" for k, v in errs.items()]
            if partes:
                return "; ".join(partes)
        return str(data)[:300]

    # -- endpoints ---------------------------------------------------------

    def current_user(self) -> dict[str, Any] | None:
        """
        Identidade do usuário atual (accountId/displayName).

        `/myself` funciona com token de API clássico. Token com scopes NÃO acessa
        `/myself` (401, exige scope de conta) — então cai para `user/search` pelo
        email. Como o Atlassian esconde email por padrão, isso pode vir vazio:
        retorna None nesse caso (identidade indisponível, não é erro).
        """
        try:
            return self._request("GET", f"{JIRA_API}/myself")
        except JiraError as e:
            if e.status != 401:
                raise
        results = self._request(
            "GET", f"{JIRA_API}/user/search", params={"query": self.email}
        )
        for usr in results or []:
            if (usr.get("emailAddress") or "").lower() == self.email.lower():
                return usr
        return results[0] if results else None

    def log_work(
        self,
        issue_key: str,
        time_spent_seconds: int,
        started: str,
        comment_adf: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "timeSpentSeconds": time_spent_seconds,
            "started": started,
        }
        if comment_adf:
            body["comment"] = comment_adf
        return self._request(
            "POST", f"{JIRA_API}/issue/{issue_key}/worklog", json_body=body
        )

    def get_worklogs(self, issue_key: str) -> dict[str, Any]:
        return self._request("GET", f"{JIRA_API}/issue/{issue_key}/worklog")

    def search_issues(self, jql: str, max_results: int = 20) -> dict[str, Any]:
        body = {
            "jql": jql,
            "maxResults": max_results,
            "fields": ["summary", "status"],
        }
        return self._request("POST", f"{JIRA_API}/search/jql", json_body=body)

    def delete_worklog(self, issue_key: str, worklog_id: str) -> dict[str, Any]:
        self._request(
            "DELETE", f"{JIRA_API}/issue/{issue_key}/worklog/{worklog_id}"
        )
        return {"deleted": worklog_id}
