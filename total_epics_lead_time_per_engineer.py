"""
Total Epics Lead Time Per Engineer — Board PT/122, calendar month.

Same attribution model as the per-sprint report: intersect each ticket's
In Progress -> Done window with its assignee timeline, so an engineer is only
credited for time they personally held the ticket while it was in progress.

The difference is scope and shape. The window is a calendar month (July 2026 by
default) rather than the active sprint, every interval is additionally clipped
to that month, and the breakdown goes one level deeper:

    Engineer -> Epic -> individual tickets, with a subtotal per Epic.

Time is counted in business days (Mon-Fri).
"""

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timezone

from tabulate import tabulate

from business_time import business_days_overlap
from jira_client import JiraClient, from_env
from timeline import build_assignee_intervals, build_work_window, resolve_epic

BOARD_ID = 122
PROJECT = "PT"
DEFAULT_MONTH = "2026-07"


def month_bounds(month: str) -> tuple[datetime, datetime]:
    """Return (start, end) UTC datetimes for a 'YYYY-MM' string; end is exclusive."""
    try:
        year, mon = (int(p) for p in month.split("-"))
        start = datetime(year, mon, 1, tzinfo=timezone.utc)
    except (ValueError, TypeError):
        raise SystemExit(f"Invalid month '{month}' — expected format YYYY-MM, e.g. 2026-07")
    end = datetime(year + (mon == 12), (mon % 12) + 1, 1, tzinfo=timezone.utc)
    return start, end


def build_jql(start: datetime, end: datetime, project: str) -> str:
    """
    Candidate tickets: anything that could plausibly have been worked during the
    month. A ticket created after the month ended cannot qualify. Anything else
    that was touched on or after the month started is a candidate, plus tickets
    still open (they may have been in progress through the month without any
    changelog activity inside it). Non-overlapping candidates contribute zero
    once intervals are clipped, so a slightly wide net is safe.
    """
    created_before = end.strftime("%Y-%m-%d")
    updated_after = start.strftime("%Y-%m-%d")
    return (
        f'project = {project} AND created < "{created_before}" '
        f'AND (updated >= "{updated_after}" OR statusCategory != Done)'
    )


def run(client: JiraClient, month: str, board_id: int = BOARD_ID, project: str = PROJECT):
    month_start, month_end = month_bounds(month)
    now = datetime.now(timezone.utc)
    if month_end > now:
        print(f"Note: {month} is not fully elapsed — capping at now ({now:%Y-%m-%d}).")
        month_end = now

    jql = build_jql(month_start, month_end, project)
    print(f"Fetching candidate issues for {month} from board {board_id} ({project})...")
    issues = client.get_sprint_issues(
        board_id, jql, fields="summary,status,assignee,parent,issuetype,created"
    )
    print(f"Found {len(issues)} candidates. Reconstructing timelines...\n")

    # engineer -> epic -> ticket -> business days
    totals: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(float))
    )
    summaries: dict[str, str] = {}
    epic_cache: dict = {}
    contributing = set()

    for i, issue in enumerate(issues, 1):
        key = issue["key"]
        print(f"  [{i}/{len(issues)}] {key}", end="\r", flush=True)

        changelog = client.get_issue_changelog(key)
        win_start, win_end, _is_open = build_work_window(changelog, client, now)
        if win_start is None:
            continue

        # Clip the work window to the reporting month before attributing.
        win_start = max(win_start, month_start)
        win_end = min(win_end, month_end)
        if win_end <= win_start:
            continue

        epic = resolve_epic(issue, client, epic_cache)
        summaries[key] = issue["fields"].get("summary", "")[:45]

        for a_start, a_end, engineer in build_assignee_intervals(changelog, issue, now):
            days = business_days_overlap(a_start, a_end, win_start, win_end)
            if days > 0:
                totals[engineer][epic][key] += days
                contributing.add(key)

    print()
    print(f"{len(contributing)} tickets had in-progress time during {month}.\n")
    return totals, summaries


def print_report(totals: dict, summaries: dict, month: str, team: str = "Board PT/122"):
    print(f"\n=== Total Epics Lead Time Per Engineer — {team} — {month} ===")
    print("Business days (Mon-Fri) each engineer held a ticket while In Progress,")
    print(f"clipped to the {month} calendar month.\n")

    if not totals:
        print(f"No in-progress work found for {month}.")
        return

    engineer_totals = {
        eng: sum(d for epics in epic_map.values() for d in epics.values())
        for eng, epic_map in totals.items()
    }

    rows = []
    for engineer in sorted(engineer_totals, key=engineer_totals.get, reverse=True):
        epic_map = totals[engineer]
        epic_totals = {e: sum(t.values()) for e, t in epic_map.items()}
        rows.append([engineer, "", "", ""])

        for epic in sorted(epic_totals, key=epic_totals.get, reverse=True):
            rows.append(["", epic, "", ""])
            tickets = epic_map[epic]
            for ticket in sorted(tickets, key=tickets.get, reverse=True):
                rows.append(["", "", f"{ticket}  {summaries.get(ticket, '')}", f"{tickets[ticket]:.1f}"])
            rows.append(["", "", "Epic subtotal", f"{epic_totals[epic]:.1f}"])

        rows.append(["", "", "ENGINEER TOTAL", f"{engineer_totals[engineer]:.1f}"])
        rows.append(["", "", "", ""])

    print(tabulate(rows, headers=["Engineer", "Epic", "Ticket", "Days"],
                   tablefmt="rounded_outline", floatfmt=".1f"))

    print("--- Summary per engineer ---")
    summary = [
        [e, f"{d:.1f}", "█" * int(d)]
        for e, d in sorted(engineer_totals.items(), key=lambda x: x[1], reverse=True)
    ]
    print(tabulate(summary, headers=["Engineer", "Total Days", ""],
                   tablefmt="rounded_outline", floatfmt=".1f"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Total epics lead time per engineer for a month.")
    parser.add_argument("--month", default=DEFAULT_MONTH, help="Month as YYYY-MM (default: 2026-07)")
    parser.add_argument("--board", type=int, default=BOARD_ID, help=f"Board id (default: {BOARD_ID})")
    parser.add_argument("--project", default=PROJECT, help=f"Project key (default: {PROJECT})")
    args = parser.parse_args()

    client = from_env()
    totals, summaries = run(client, args.month, args.board, args.project)
    print_report(totals, summaries, args.month, f"Board {args.project}/{args.board}")
