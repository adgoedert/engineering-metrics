import os
import base64
import requests


class JiraClient:
    def __init__(self, domain: str, email: str, token: str):
        self.base_url = f"{domain.rstrip('/')}/rest/api/3"
        credentials = base64.b64encode(f"{email}:{token}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def get(self, path: str, params: dict = None):
        url = f"{self.base_url}{path}"
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()

    def get_board_config(self, board_id: int):
        url = f"{self.base_url.replace('/rest/api/3', '')}/rest/agile/1.0/board/{board_id}/configuration"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def get_issues_in_column(self, board_id: int, jql: str, start: int = 0, max_results: int = 100):
        url = f"{self.base_url.replace('/rest/api/3', '')}/rest/agile/1.0/board/{board_id}/issue"
        params = {"jql": jql, "startAt": start, "maxResults": max_results, "fields": "summary,status,created"}
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()

    def get_sprint_issues(self, board_id: int, jql: str, fields: str = "summary,status,parent,issuetype") -> list[dict]:
        """Fetch all issues matching a JQL query for a board, paginating automatically."""
        issues = []
        start = 0
        while True:
            url = f"{self.base_url.replace('/rest/api/3', '')}/rest/agile/1.0/board/{board_id}/issue"
            params = {"jql": jql, "startAt": start, "maxResults": 100, "fields": fields}
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            batch = data.get("issues", [])
            issues.extend(batch)
            start += len(batch)
            if start >= data.get("total", 0) or not batch:
                break
        return issues

    def list_boards(self, name: str = None, project_key: str = None) -> list[dict]:
        """List agile boards, optionally filtered by name substring or project."""
        boards = []
        start = 0
        while True:
            url = f"{self.base_url.replace('/rest/api/3', '')}/rest/agile/1.0/board"
            params = {"startAt": start, "maxResults": 50}
            if name:
                params["name"] = name
            if project_key:
                params["projectKeyOrId"] = project_key
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            batch = data.get("values", [])
            boards.extend(batch)
            start += len(batch)
            if data.get("isLast", True) or not batch:
                break
        return boards

    def resolve_board_for_project(self, project_key: str) -> int:
        """
        The board id for a project. Projects often carry more than one board,
        and picking the wrong one silently changes which tickets a report sees,
        so an ambiguous result is an error asking for --board rather than a guess.
        """
        boards = self.list_boards(project_key=project_key)
        if not boards:
            raise SystemExit(
                f"No board found for project {project_key}.\n"
                f"Run './run.sh boards' to list the boards you can access."
            )
        if len(boards) > 1:
            listing = "\n".join(
                f"  --board {b['id']:<6} {b.get('name', '')} ({b.get('type', '')})"
                for b in boards
            )
            raise SystemExit(
                f"Project {project_key} has {len(boards)} boards — pick one explicitly:\n{listing}"
            )
        return boards[0]["id"]

    def get_issue(self, issue_key: str, fields: str = "summary,parent,issuetype") -> dict:
        return self.get(f"/issue/{issue_key}", params={"fields": fields})

    def resolve_status_category(self, status_id: str, status_name: str = "") -> str:
        """
        Map a status id to its category name ("To Do" / "In Progress" / "Done").
        Changelog entries only carry the status id and name, not the category,
        so we look it up once and cache it.
        """
        if not hasattr(self, "_status_category_cache"):
            self._status_category_cache = {}
        if status_id in self._status_category_cache:
            return self._status_category_cache[status_id]
        try:
            data = self.get(f"/status/{status_id}")
            category = data.get("statusCategory", {}).get("name", "")
        except Exception:
            name_lower = (status_name or "").lower()
            if any(w in name_lower for w in ("done", "closed", "resolved")):
                category = "Done"
            elif any(w in name_lower for w in ("progress", "review", "testing")):
                category = "In Progress"
            else:
                category = "To Do"
        self._status_category_cache[status_id] = category
        return category

    def get_issue_changelog(self, issue_key: str):
        """Fetch full changelog for an issue, paginating as needed."""
        entries = []
        start = 0
        while True:
            data = self.get(f"/issue/{issue_key}/changelog", params={"startAt": start, "maxResults": 100})
            entries.extend(data.get("values", []))
            if data.get("isLast", True):
                break
            start += len(data["values"])
        return entries


def from_env():
    domain = os.environ.get("JIRA_DOMAIN", "https://surepay.atlassian.net")
    email = os.environ.get("JIRA_EMAIL", "Alexandre.goedert@surepay.nl")
    token = os.environ.get("JIRA_API_TOKEN", "")
    if not token:
        raise ValueError("JIRA_API_TOKEN environment variable is not set")
    return JiraClient(domain, email, token)
