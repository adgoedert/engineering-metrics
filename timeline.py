"""
Reconstructing ticket timelines from the Jira changelog.

Shared by the per-engineer reports. Two timelines matter:

  1. The "work window": from the first transition INTO an "In Progress" status
     to the first transition INTO a "Done" status.
  2. The assignee timeline: who held the ticket, between which timestamps.

Intersecting the two gives the time an engineer personally held a ticket while
it was actively in progress.
"""

from datetime import datetime

from dateutil import parser as dateparser

from jira_client import JiraClient

NO_EPIC = "— No Epic —"


def parse_ts(ts: str) -> datetime:
    return dateparser.parse(ts)


def build_work_window(changelog: list, client: JiraClient, now: datetime):
    """
    Return (start, end, is_open) for the In Progress -> Done window.
    start is None if the ticket never entered In Progress. Tickets that started
    but never reached Done are capped at `now` and flagged open.
    """
    first_in_progress = None
    first_done = None

    for entry in changelog:
        ts = parse_ts(entry["created"])
        for item in entry.get("items", []):
            if item.get("field") != "status":
                continue
            category = client.resolve_status_category(item.get("to", ""), item.get("toString", ""))
            if category == "In Progress" and first_in_progress is None:
                first_in_progress = ts
            elif category == "Done" and first_done is None:
                first_done = ts

    if first_in_progress is None:
        return None, None, False

    if first_done is None or first_done < first_in_progress:
        return first_in_progress, now, True

    return first_in_progress, first_done, False


def build_assignee_intervals(changelog: list, issue: dict, now: datetime) -> list[tuple]:
    """
    Return a list of (start, end, engineer_name) covering the whole life of the
    ticket. The changelog only records *changes*, so the holder before the first
    change is recovered from that change's `fromString`.
    """
    created = parse_ts(issue["fields"]["created"])
    current = issue["fields"].get("assignee")
    current_name = current.get("displayName") if current else None

    changes = []
    for entry in changelog:
        ts = parse_ts(entry["created"])
        for item in entry.get("items", []):
            if item.get("field") == "assignee":
                changes.append((ts, item.get("fromString"), item.get("toString")))
    changes.sort(key=lambda c: c[0])

    intervals = []
    if not changes:
        # Never reassigned: whoever holds it now held it from creation.
        if current_name:
            intervals.append((created, now, current_name))
        return intervals

    # Segment before the first recorded change.
    first_ts, first_from, _ = changes[0]
    if first_from:
        intervals.append((created, first_ts, first_from))

    for i, (ts, _from_name, to_name) in enumerate(changes):
        end = changes[i + 1][0] if i + 1 < len(changes) else now
        if to_name:
            intervals.append((ts, end, to_name))

    return intervals


def resolve_epic(issue: dict, client: JiraClient, cache: dict) -> str:
    """
    Walk up the parent chain to the nearest Epic. Falls back to the direct
    parent if no ancestor is explicitly typed as an Epic.
    """
    key = issue["key"]
    if key in cache:
        return cache[key]

    parent = issue["fields"].get("parent")
    if not parent:
        cache[key] = NO_EPIC
        return NO_EPIC

    direct_parent = parent.get("key")
    current_key = direct_parent
    seen = set()

    while current_key and current_key not in seen:
        seen.add(current_key)
        if current_key in cache:
            cache[key] = cache[current_key]
            return cache[key]
        try:
            data = client.get_issue(current_key, fields="summary,parent,issuetype")
        except Exception:
            break
        fields = data.get("fields", {})
        issue_type = fields.get("issuetype", {}).get("name", "")
        if issue_type.lower() == "epic":
            summary = fields.get("summary", "")[:40]
            label = f"{current_key} {summary}"
            cache[key] = label
            cache[current_key] = label
            return label
        next_parent = fields.get("parent")
        current_key = next_parent.get("key") if next_parent else None

    # No Epic ancestor found — attribute to the direct parent.
    label = f"{direct_parent} (no epic ancestor)"
    cache[key] = label
    return label
