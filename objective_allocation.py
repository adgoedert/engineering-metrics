"""
Objective Allocation Report — Board PT/122, Active Sprint.

For every ticket in the active sprint, walks up the parent chain until it
finds one of the known high-level Objectives (or marks the ticket as orphan).
Reports the percentage of tickets per Objective.
"""

from tabulate import tabulate
from jira_client import JiraClient, from_env

BOARD_ID = 122
PROJECT = "PT"

# Known top-level Objectives (Epic / Initiative keys)
OBJECTIVES = {"PM-409", "PM-410", "PM-407", "PM-408", "PM-35", "PM-265", "PM-414", "PM-391"}


def _get_parent_key(issue: dict) -> str | None:
    """Extract the direct parent key from an issue dict (fields.parent)."""
    fields = issue.get("fields", {})
    parent = fields.get("parent")
    if parent:
        return parent.get("key")
    return None


def resolve_objective(issue_key: str, issue_fields: dict, client: JiraClient, cache: dict) -> str | None:
    """
    Walk up the parent chain from `issue_key` until we hit an Objective or run out.
    Returns the Objective key, or None if the ticket is an orphan.
    Uses `cache` to avoid redundant API calls.
    """
    visited = []
    current_key = issue_key
    current_fields = issue_fields

    while True:
        if current_key in cache:
            result = cache[current_key]
            # Back-fill all visited keys with the resolved result
            for k in visited:
                cache[k] = result
            return result

        if current_key in OBJECTIVES:
            for k in visited + [current_key]:
                cache[k] = current_key
            return current_key

        parent_key = _get_parent_key({"fields": current_fields})
        if not parent_key:
            # No further parent — orphan
            for k in visited + [current_key]:
                cache[k] = None
            return None

        visited.append(current_key)
        # Fetch the parent
        try:
            parent_issue = client.get_issue(parent_key, fields="summary,parent,issuetype")
            current_key = parent_key
            current_fields = parent_issue.get("fields", {})
        except Exception:
            for k in visited + [current_key]:
                cache[k] = None
            return None


def run(client: JiraClient, board_id: int = BOARD_ID):
    jql = f"project = {PROJECT} AND sprint in openSprints()"
    print(f"Fetching all active sprint issues from board {board_id}...")
    issues = client.get_sprint_issues(board_id, jql, fields="summary,status,parent,issuetype")
    total = len(issues)
    print(f"Found {total} issues. Resolving objectives...\n")

    # Resolve each issue to an Objective
    cache: dict = {}
    allocation: dict[str | None, list[str]] = {}  # objective_key -> [issue_keys]

    for i, issue in enumerate(issues, 1):
        key = issue["key"]
        fields = issue.get("fields", {})
        print(f"  [{i}/{total}] {key}", end="\r", flush=True)
        obj = resolve_objective(key, fields, client, cache)
        allocation.setdefault(obj, []).append(key)

    print()  # newline after progress
    return allocation, total


def _obj_label(obj_key: str | None, client: JiraClient, summary_cache: dict) -> str:
    if obj_key is None:
        return "— Orphan (no objective) —"
    if obj_key not in summary_cache:
        try:
            data = client.get_issue(obj_key, fields="summary")
            summary_cache[obj_key] = data["fields"].get("summary", "")[:50]
        except Exception:
            summary_cache[obj_key] = ""
    summary = summary_cache.get(obj_key, "")
    return f"{obj_key}  {summary}"


def print_report(allocation: dict, total: int, client: JiraClient):
    summary_cache: dict = {}

    rows = []
    for obj_key, keys in sorted(
        allocation.items(),
        key=lambda x: len(x[1]),
        reverse=True,
    ):
        count = len(keys)
        pct = count / total * 100 if total else 0
        bar = "█" * int(pct / 2)  # 50-char max bar
        rows.append([
            _obj_label(obj_key, client, summary_cache),
            count,
            f"{pct:.1f}%",
            bar,
        ])

    print("\n=== Objective Allocation Report — Board PT/122 (Active Sprint) ===\n")
    print(tabulate(rows, headers=["Objective", "Tickets", "%", ""], tablefmt="rounded_outline"))
    print(f"\nTotal tickets in active sprint: {total}")

    # Detailed orphan list
    orphans = allocation.get(None, [])
    if orphans:
        print(f"\nOrphan tickets ({len(orphans)}): {', '.join(orphans)}")


if __name__ == "__main__":
    client = from_env()
    allocation, total = run(client)
    print_report(allocation, total, client)
