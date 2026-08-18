"""
Lead time report: time from first transition INTO "To Do" (or ticket creation)
to first transition INTO a "Done" category status, for all Done tickets on a board.
"""

import sys
from datetime import datetime, timezone
from dateutil import parser as dateparser
from tabulate import tabulate
from business_time import business_days_between
from jira_client import JiraClient, from_env


BOARD_ID = 122
DONE_STATUS_CATEGORY = "Done"


def find_transition_timestamps(changelog: list, from_status_category: str, to_status_category: str, client: JiraClient):
    """
    Return (first_todo_ts, first_done_ts) from a list of changelog entries.
    We look at status field changes and use the statusCategory to bucket them.
    """
    first_todo = None
    first_done = None

    for entry in changelog:
        created = dateparser.parse(entry["created"])
        for item in entry.get("items", []):
            if item.get("field") != "status":
                continue
            to_string = item.get("toString", "")
            to_id = item.get("to", "")
            # We resolve status category via the status name heuristic;
            # changelog doesn't give category directly, so we use the status id lookup.
            category = _resolve_category(to_id, to_string, client)
            if category == "To Do" and first_todo is None:
                first_todo = created
            if category == "Done" and first_done is None:
                first_done = created

    return first_todo, first_done


_category_cache: dict[str, str] = {}


def _resolve_category(status_id: str, status_name: str, client: JiraClient) -> str:
    """Cache-backed lookup of a status's category name."""
    if status_id in _category_cache:
        return _category_cache[status_id]
    try:
        data = client.get(f"/status/{status_id}")
        category = data.get("statusCategory", {}).get("name", "")
    except Exception:
        # Fallback: guess from name
        name_lower = status_name.lower()
        if "done" in name_lower or "closed" in name_lower or "resolved" in name_lower:
            category = "Done"
        elif "progress" in name_lower or "review" in name_lower:
            category = "In Progress"
        else:
            category = "To Do"
    _category_cache[status_id] = category
    return category


def fetch_all_done_issues(client: JiraClient, board_id: int) -> list[dict]:
    """Fetch all issues currently in a Done status category in the active sprint on the board."""
    jql = f'project = PT AND statusCategory = Done AND sprint in openSprints() ORDER BY updated DESC'
    issues = []
    start = 0
    while True:
        data = client.get_issues_in_column(board_id, jql, start=start, max_results=100)
        batch = data.get("issues", [])
        issues.extend(batch)
        total = data.get("total", 0)
        start += len(batch)
        if start >= total or not batch:
            break
    return issues


def compute_lead_times(client: JiraClient, board_id: int) -> list[dict]:
    print(f"Fetching Done issues from board {board_id}...")
    issues = fetch_all_done_issues(client, board_id)
    print(f"Found {len(issues)} Done issues. Fetching changelogs...")

    rows = []
    for i, issue in enumerate(issues, 1):
        key = issue["key"]
        summary = issue["fields"].get("summary", "")[:60]
        created_str = issue["fields"].get("created", "")
        created_ts = dateparser.parse(created_str) if created_str else None

        print(f"  [{i}/{len(issues)}] {key}", end="\r", flush=True)
        changelog = client.get_issue_changelog(key)
        first_todo, first_done = find_transition_timestamps(changelog, "To Do", "Done", client)

        # Use ticket creation as fallback for "To Do" start
        start_ts = first_todo or created_ts
        if start_ts and first_done and first_done > start_ts:
            lead_days = round(business_days_between(start_ts, first_done), 1)
        else:
            lead_days = None

        rows.append({
            "key": key,
            "summary": summary,
            "created": created_ts.strftime("%Y-%m-%d") if created_ts else "?",
            "todo_ts": start_ts.strftime("%Y-%m-%d") if start_ts else "?",
            "done_ts": first_done.strftime("%Y-%m-%d") if first_done else "?",
            "lead_days": lead_days,
        })

    print()  # newline after progress
    return rows


def print_report(rows: list[dict]):
    valid = [r for r in rows if r["lead_days"] is not None]
    invalid = [r for r in rows if r["lead_days"] is None]

    table = [
        [r["key"], r["summary"], r["todo_ts"], r["done_ts"], r["lead_days"]]
        for r in sorted(valid, key=lambda x: x["lead_days"], reverse=True)
    ]

    print("\n=== Lead Time Report — Board PT/122 (Active Sprint, Done tickets) ===\n")
    print(tabulate(table, headers=["Key", "Summary", "Start", "Done", "Lead Days (bus.)"], tablefmt="rounded_outline"))

    if valid:
        avg = sum(r["lead_days"] for r in valid) / len(valid)
        median = sorted(r["lead_days"] for r in valid)[len(valid) // 2]
        print(f"\nTotal issues: {len(rows)}  |  Computed: {len(valid)}  |  Skipped: {len(invalid)}")
        print(f"Average lead time : {avg:.1f} days")
        print(f"Median lead time  : {median:.1f} days")

    if invalid:
        print(f"\nSkipped (incomplete data): {', '.join(r['key'] for r in invalid)}")


if __name__ == "__main__":
    client = from_env()
    rows = compute_lead_times(client, BOARD_ID)
    print_report(rows)
