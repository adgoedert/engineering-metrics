"""
Epics Lead Time Per Engineer — Board PT/122, Active Sprint.

For every ticket in the active sprint, intersects the In Progress -> Done
window with the assignee timeline (see timeline.py) to get the time each
engineer personally held the ticket while it was in progress, rolled up
per Epic. Time is counted in business days.
"""

from collections import defaultdict
from datetime import datetime, timezone

from tabulate import tabulate

from business_time import business_days_overlap as overlap_days
from jira_client import JiraClient, from_env
from timeline import build_assignee_intervals, build_work_window, resolve_epic

BOARD_ID = 122
PROJECT = "PT"


def run(client: JiraClient, board_id: int = BOARD_ID):
    now = datetime.now(timezone.utc)
    jql = f"project = {PROJECT} AND sprint in openSprints()"

    print(f"Fetching all active sprint issues from board {board_id}...")
    issues = client.get_sprint_issues(
        board_id, jql, fields="summary,status,assignee,parent,issuetype,created"
    )
    print(f"Found {len(issues)} issues. Reconstructing timelines...\n")

    # engineer -> epic -> days
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    epic_cache: dict = {}
    open_tickets = []
    never_started = []

    for i, issue in enumerate(issues, 1):
        key = issue["key"]
        print(f"  [{i}/{len(issues)}] {key}", end="\r", flush=True)

        changelog = client.get_issue_changelog(key)
        win_start, win_end, is_open = build_work_window(changelog, client, now)

        if win_start is None:
            never_started.append(key)
            continue
        if is_open:
            open_tickets.append(key)

        epic = resolve_epic(issue, client, epic_cache)

        for a_start, a_end, engineer in build_assignee_intervals(changelog, issue, now):
            days = overlap_days(a_start, a_end, win_start, win_end)
            if days > 0:
                totals[engineer][epic] += days

    print()
    return totals, open_tickets, never_started


def print_report(totals: dict, open_tickets: list, never_started: list):
    print("\n=== Epics Lead Time Per Engineer — Board PT/122 (Active Sprint) ===")
    print("Time is business days (Mon-Fri) each engineer held a ticket while it was In Progress.\n")

    if not totals:
        print("No in-progress work found for the active sprint.")
        return

    rows = []
    engineer_totals = {e: sum(epics.values()) for e, epics in totals.items()}

    for engineer in sorted(engineer_totals, key=engineer_totals.get, reverse=True):
        epics = totals[engineer]
        first = True
        for epic in sorted(epics, key=epics.get, reverse=True):
            rows.append([
                engineer if first else "",
                epic,
                f"{epics[epic]:.1f}",
            ])
            first = False
        rows.append(["", "TOTAL", f"{engineer_totals[engineer]:.1f}"])
        rows.append(["", "", ""])

    print(tabulate(rows, headers=["Engineer", "Epic", "Days"], tablefmt="rounded_outline"))

    print("\n--- Summary per engineer ---")
    summary = [
        [e, f"{d:.1f}", "█" * int(d)]
        for e, d in sorted(engineer_totals.items(), key=lambda x: x[1], reverse=True)
    ]
    print(tabulate(summary, headers=["Engineer", "Total Days", ""], tablefmt="rounded_outline"))

    if open_tickets:
        print(f"\nStill in progress (time counted up to now): {', '.join(open_tickets)}")
    if never_started:
        print(f"Never entered In Progress (excluded): {', '.join(never_started)}")


if __name__ == "__main__":
    client = from_env()
    totals, open_tickets, never_started = run(client)
    print_report(totals, open_tickets, never_started)
