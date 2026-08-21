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

The team's Jira project is read from epics-mapping.csv: the "Project name"
column holds the team name ("Team Horizon") and "Project key" the Jira key
("SUK"). The two bear no resemblance, so the CSV is the only reliable way to
map between them — a board-name search finds nothing for "Horizon". The board
id is then looked up from that project key.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone

from tabulate import tabulate

from business_time import business_days_touched, intersect
from jira_client import from_env
from timeline import build_assignee_intervals, build_work_window, resolve_epic_ref
from total_epics_lead_time_per_engineer import DEFAULT_MONTH, month_bounds, build_jql
from wbso import DEFAULT_CSV, load_mapping

TEAM_NAME = "Team Horizon"
HOURS_PER_DAY = 8.0


def run(client, month: str, board_id: int, project: str, wbso_epics: set = None, flags: dict = None):
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
    epic_of: dict[str, tuple] = {}
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
            epic_of[key] = resolve_epic_ref(issue, client, epic_cache)
            summaries[key] = issue["fields"].get("summary", "")[:45]

    print()

    # Split each engineer-day's 8 hours equally across that day's active tickets.
    #
    # When filtering to WBSO, the denominator stays the FULL set of tickets held
    # that day — only the output is filtered. An engineer who held one WBSO and
    # two non-WBSO tickets on Tuesday spent 8/3h on the WBSO one, not 8h. Using
    # the filtered count as the denominator would inflate the WBSO total, which
    # for a subsidy claim is the wrong direction to be wrong in.
    totals: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(float))
    )
    busiest = {}
    capacity_hours: dict[str, float] = defaultdict(float)
    kept_tickets, excluded_tickets, unmapped_epics = set(), set(), {}
    wbso_other_team = {}

    for engineer, by_day in active.items():
        for day, tickets in by_day.items():
            share = HOURS_PER_DAY / len(tickets)
            if len(tickets) > busiest.get(engineer, (0, None))[0]:
                busiest[engineer] = (len(tickets), day)
            capacity_hours[engineer] += HOURS_PER_DAY
            for ticket in tickets:
                epic_key, epic_label = epic_of[ticket]
                if wbso_epics is not None:
                    if epic_key is None or epic_key not in wbso_epics:
                        excluded_tickets.add(ticket)
                        if epic_key and flags is not None:
                            if epic_key not in flags:
                                unmapped_epics[epic_key] = ticket
                            elif flags[epic_key] == "yes":
                                # Flagged WBSO, but under another team's rows.
                                wbso_other_team[epic_key] = ticket
                        continue
                kept_tickets.add(ticket)
                totals[engineer][epic_label][ticket] += share

    day_counts = {e: len(by_day) for e, by_day in active.items()}
    print(f"{len(epic_of)} tickets had in-progress time during {month}.")
    if wbso_epics is not None:
        print(f"{len(kept_tickets)} are under a WBSO epic; {len(excluded_tickets)} filtered out.")
    print()

    diagnostics = {
        "capacity_hours": dict(capacity_hours),
        "excluded": excluded_tickets,
        "unmapped_epics": unmapped_epics,
        "wbso_other_team": wbso_other_team,
        "filtered": wbso_epics is not None,
    }
    return totals, summaries, day_counts, busiest, diagnostics


def print_report(totals, summaries, day_counts, busiest, month, team, diagnostics=None):
    diagnostics = diagnostics or {}
    filtered = diagnostics.get("filtered")
    scope = " — WBSO epics only" if filtered else ""

    print(f"\n=== Total Epics Lead Time Per Engineer — {team} — {month}{scope} ===")
    print(f"Capacity model: max {HOURS_PER_DAY:.0f}h per engineer per business day,")
    print("split equally across every ticket that engineer held In Progress that day.")
    if filtered:
        print("Shares are computed over ALL tickets held that day, then filtered to")
        print("WBSO epics — so hours here are never inflated by the filter.")
    print()

    if not totals:
        if filtered:
            print(f"No WBSO-epic work found for {month}.")
            print("Either this team's epics are not flagged 'yes' in the mapping,")
            print("or their epics are absent from it. Check with:")
            print("  ./run.sh boards Horizon    # confirm the board/project")
            unmapped = diagnostics.get("unmapped_epics") or {}
            if unmapped:
                print(f"\nEpics worked on but absent from the mapping: {', '.join(sorted(unmapped))}")
        else:
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
    capacity = diagnostics.get("capacity_hours", {})
    summary = []
    for eng, hours in sorted(engineer_totals.items(), key=lambda x: x[1], reverse=True):
        peak, peak_day = busiest.get(eng, (0, None))
        row = [
            eng,
            f"{hours:.1f}",
            f"{hours / HOURS_PER_DAY:.1f}",
            day_counts.get(eng, 0),
            f"{peak} on {peak_day:%d %b}" if peak_day else "-",
        ]
        if filtered:
            total_cap = capacity.get(eng, 0)
            row.append(f"{hours / total_cap * 100:.0f}%" if total_cap else "-")
        summary.append(row)

    headers = ["Engineer", "Hours", "Days", "Active days", "Peak tickets/day"]
    if filtered:
        headers.append("WBSO share")
    print(tabulate(summary, headers=headers, tablefmt="rounded_outline", floatfmt=".1f"))

    if filtered:
        total_wbso = sum(engineer_totals.values())
        total_cap = sum(capacity.values())
        if total_cap:
            print(f"\nTeam WBSO hours: {total_wbso:.1f} of {total_cap:.1f} "
                  f"capacity hours ({total_wbso / total_cap * 100:.0f}%)")
        unmapped = diagnostics.get("unmapped_epics") or {}
        if unmapped:
            print(f"\nWarning: {len(unmapped)} epic(s) worked on this month are absent from")
            print(f"the mapping entirely (not 'yes' or 'no'): {', '.join(sorted(unmapped))}")
            print("These were treated as non-WBSO. Add them to the CSV if that is wrong.")

        other = diagnostics.get("wbso_other_team") or {}
        if other:
            print(f"\nNote: {len(other)} epic(s) worked on are flagged WBSO, but under another")
            print(f"team's rows, so they were excluded: {', '.join(sorted(other))}")
            print("Re-run with --wbso-all-teams to include them.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Total epics lead time per engineer — Team Horizon, 8h/day capacity model."
    )
    parser.add_argument("--month", default=DEFAULT_MONTH, help="Month as YYYY-MM (default: 2026-07)")
    parser.add_argument("--team", default=TEAM_NAME,
                        help=f"Team name as it appears in the mapping (default: {TEAM_NAME})")
    parser.add_argument("--board", type=int, default=None,
                        help="Board id (default: look up from the team's project)")
    parser.add_argument("--project", default=None,
                        help="Project key (default: read from the mapping CSV)")
    parser.add_argument("--wbso", action="store_true",
                        help="Only count tickets under epics flagged 'yes' in the mapping")
    parser.add_argument("--wbso-all-teams", action="store_true",
                        help="With --wbso, accept epics flagged 'yes' under any team, "
                             "not just this one")
    parser.add_argument("--mapping-file", default=DEFAULT_CSV,
                        help=f"Path to the epic mapping CSV (default: {DEFAULT_CSV})")
    args = parser.parse_args()

    mapping = load_mapping(args.mapping_file)

    if args.project:
        team, project = args.team, args.project
    else:
        team, project = mapping.project_for_team(args.team)
        print(f"'{args.team}' -> {team}, Jira project {project} (from mapping CSV)")

    wbso_epics = flags = None
    if args.wbso:
        scope = None if args.wbso_all_teams else team
        wbso_epics = mapping.wbso_epics(scope)
        flags = mapping.flags()
        print(f"WBSO mapping: {mapping.summarise(scope)}")
        if not wbso_epics:
            raise SystemExit(
                f"No epics are flagged 'yes' for {team}. Nothing to report.\n"
                f"Use --wbso-all-teams to accept any team's WBSO epics."
            )

    client = from_env()

    board_id = args.board
    if board_id is None:
        board_id = client.resolve_board_for_project(project)
    print(f"Using board {board_id} (project {project}).\n")

    totals, summaries, day_counts, busiest, diagnostics = run(
        client, args.month, board_id, project, wbso_epics, flags
    )
    print_report(
        totals, summaries, day_counts, busiest, args.month,
        f"{team} (board {project}/{board_id})", diagnostics,
    )
