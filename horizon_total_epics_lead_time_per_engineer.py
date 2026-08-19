"""
Total Epics Lead Time Per Engineer — Team Horizon, calendar month, capped at 8h/day.

Same source data as the other per-engineer reports, but a different accounting
model. The earlier reports measure *elapsed* time, so an engineer holding three
tickets across the same week is credited five days on each — fifteen days out of
a five-day week. This report measures *capacity* instead:

  - A day is the indivisible unit. Any weekday on which an engineer held a
    ticket while it was In Progress makes that ticket active for them that day.
  - Each engineer-day is worth at most 8 hours.
  - Those 8 hours are split equally across every ticket active that day.

So three tickets on Tuesday give 2h40m each, not 8h each. An engineer's monthly
total can therefore never exceed 8h x (business days in the month).

Board and project are resolved at runtime by name, as with the Ikigai report.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone

from tabulate import tabulate

from business_time import business_days_touched, intersect
from jira_client import from_env
from timeline import build_assignee_intervals, build_work_window, resolve_epic
from total_epics_lead_time_per_engineer import DEFAULT_MONTH, month_bounds, build_jql

TEAM_NAME = "Horizon"
HOURS_PER_DAY = 8.0


def run(client, month: str, board_id: int, project: str):
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

    # engineer -> date -> {ticket keys active that day}
    active: dict[str, dict] = defaultdict(lambda: defaultdict(set))
    epic_of: dict[str, str] = {}
    summaries: dict[str, str] = {}
    epic_cache: dict = {}

    for i, issue in enumerate(issues, 1):
        key = issue["key"]
        print(f"  [{i}/{len(issues)}] {key}", end="\r", flush=True)

        changelog = client.get_issue_changelog(key)
        win_start, win_end, _is_open = build_work_window(changelog, client, now)
        if win_start is None:
            continue

        window = intersect(win_start, win_end, month_start, month_end)
        if window is None:
            continue
        win_start, win_end = window

        recorded = False
        for a_start, a_end, engineer in build_assignee_intervals(changelog, issue, now):
            segment = intersect(a_start, a_end, win_start, win_end)
            if segment is None:
                continue
            for day in business_days_touched(*segment):
                active[engineer][day].add(key)
                recorded = True

        if recorded:
            epic_of[key] = resolve_epic(issue, client, epic_cache)
            summaries[key] = issue["fields"].get("summary", "")[:45]

    print()

    # Split each engineer-day's 8 hours equally across that day's active tickets.
    totals: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(float))
    )
    busiest = {}
    for engineer, by_day in active.items():
        for day, tickets in by_day.items():
            share = HOURS_PER_DAY / len(tickets)
            if len(tickets) > busiest.get(engineer, (0, None))[0]:
                busiest[engineer] = (len(tickets), day)
            for ticket in tickets:
                totals[engineer][epic_of[ticket]][ticket] += share

    day_counts = {e: len(by_day) for e, by_day in active.items()}
    print(f"{len(epic_of)} tickets had in-progress time during {month}.\n")
    return totals, summaries, day_counts, busiest


def print_report(totals, summaries, day_counts, busiest, month, team):
    print(f"\n=== Total Epics Lead Time Per Engineer — {team} — {month} ===")
    print(f"Capacity model: max {HOURS_PER_DAY:.0f}h per engineer per business day,")
    print("split equally across every ticket that engineer held In Progress that day.\n")

    if not totals:
        print(f"No in-progress work found for {month}.")
        return

    engineer_totals = {
        eng: sum(h for epics in epic_map.values() for h in epics.values())
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
                rows.append(
                    ["", "", f"{ticket}  {summaries.get(ticket, '')}", f"{tickets[ticket]:.1f}"]
                )
            rows.append(["", "", "Epic subtotal", f"{epic_totals[epic]:.1f}"])

        rows.append(["", "", "ENGINEER TOTAL", f"{engineer_totals[engineer]:.1f}"])
        rows.append(["", "", "", ""])

    print(tabulate(rows, headers=["Engineer", "Epic", "Ticket", "Hours"],
                   tablefmt="rounded_outline", floatfmt=".1f"))

    print("--- Summary per engineer ---")
    summary = []
    for eng, hours in sorted(engineer_totals.items(), key=lambda x: x[1], reverse=True):
        peak, peak_day = busiest.get(eng, (0, None))
        summary.append([
            eng,
            f"{hours:.1f}",
            f"{hours / HOURS_PER_DAY:.1f}",
            day_counts.get(eng, 0),
            f"{peak} on {peak_day:%d %b}" if peak_day else "-",
        ])
    print(tabulate(
        summary,
        headers=["Engineer", "Hours", "Days", "Active days", "Peak tickets/day"],
        tablefmt="rounded_outline",
        floatfmt=".1f",
    ))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Total epics lead time per engineer — Team Horizon, 8h/day capacity model."
    )
    parser.add_argument("--month", default=DEFAULT_MONTH, help="Month as YYYY-MM (default: 2026-07)")
    parser.add_argument("--board", type=int, default=None, help="Board id (default: resolve by name)")
    parser.add_argument("--project", default=None, help="Project key (default: resolve by name)")
    args = parser.parse_args()

    client = from_env()

    if args.board and args.project:
        board_id, project = args.board, args.project
    else:
        print(f"Resolving board for '{TEAM_NAME}'...")
        board_id, project = client.resolve_board_by_name(TEAM_NAME)
        board_id = args.board or board_id
        project = args.project or project
        print(f"Using board {board_id} (project {project}).\n")

    totals, summaries, day_counts, busiest = run(client, args.month, board_id, project)
    print_report(
        totals, summaries, day_counts, busiest, args.month,
        f"Team {TEAM_NAME} (board {project}/{board_id})",
    )
