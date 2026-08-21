"""
Why is a team's sheet empty?

Walks the same pipeline as the report for one team and prints what survives each
stage, so an empty result points at a cause: wrong board, JQL matching nothing,
tickets never in progress, or the WBSO epic filter removing everything.

    ./run.sh diagnose "Team Ikigai"
    ./run.sh diagnose "Team Samba" --month 2025-07
"""

import argparse

from consolidated_wbso_hours import DEFAULT_BOARD_OVERRIDES, DEFAULT_MONTH, parse_board_overrides
from horizon_total_epics_lead_time_per_engineer import run
from jira_client import from_env
from total_epics_lead_time_per_engineer import build_jql, month_bounds
from wbso import DEFAULT_CSV, load_mapping


def main():
    parser = argparse.ArgumentParser(description="Diagnose an empty team sheet.")
    parser.add_argument("team", help="Team name as it appears in the mapping CSV")
    parser.add_argument("--month", default=DEFAULT_MONTH)
    parser.add_argument("--board", action="append", default=None, metavar="TEAM=ID|NAME")
    parser.add_argument("--mapping-file", default=DEFAULT_CSV)
    args = parser.parse_args()

    mapping = load_mapping(args.mapping_file)
    team, project = mapping.project_for_team(args.team)
    wbso = mapping.wbso_epics(team)
    flags = mapping.flags()

    print(f"\n=== Diagnosing {team} for {args.month} ===\n")
    print(f"1. Mapping CSV")
    print(f"   team name        : {team}")
    print(f"   Jira project     : {project}")
    print(f"   WBSO epics       : {len(wbso)}")
    if not wbso:
        print("\n   STOP: no epics flagged 'yes' for this team. Nothing can be reported.")
        return
    print(f"   sample epic keys : {', '.join(sorted(wbso)[:6])}")

    overrides = parse_board_overrides(args.board, DEFAULT_BOARD_OVERRIDES)
    pin = overrides.get(team)
    client = from_env()

    print(f"\n2. Board")
    print(f"   pinned as        : {pin!r}" if pin is not None else "   pinned as        : (not pinned)")
    try:
        if isinstance(pin, str):
            board_id = client.resolve_board_named(project, pin)
        elif pin is None:
            board_id = client.resolve_board_for_project(project)
        else:
            board_id = pin
        print(f"   board id         : {board_id}")
    except SystemExit as exc:
        print(f"\n   STOP: {exc}")
        return

    try:
        board = client.get_board(board_id)
        board_project = (board.get("location") or {}).get("projectKey", "")
        print(f"   board name       : {board.get('name', '?')}")
        print(f"   board type       : {board.get('type', '?')}")
        print(f"   board's project  : {board_project or '(none reported)'}")
        if board_project and board_project != project:
            print(f"\n   PROBLEM: this board is in {board_project}, but {team} maps to {project}.")
            print(f"   The report filters on 'project = {project}', so the intersection is empty.")
            print(f"   Available boards for {project}:")
            for b in client.list_boards(project_key=project):
                print(f"     id={b['id']:<6} {b.get('name','')} ({b.get('type','')})")
            return
    except Exception as exc:
        print(f"   ! could not fetch board details: {type(exc).__name__}: {exc}")

    start, end = month_bounds(args.month)
    jql = build_jql(start, end, project)
    print(f"\n3. Candidate query")
    print(f"   JQL              : {jql}")
    issues = client.get_sprint_issues(
        board_id, jql, fields="summary,status,assignee,parent,issuetype,created"
    )
    print(f"   issues returned  : {len(issues)}")
    if not issues:
        print(f"\n   PROBLEM: board {board_id} returned no issues for this JQL.")
        print(f"   Check that the board's filter includes {project} issues, and that")
        print(f"   the project had activity in {args.month}.")
        return
    print(f"   sample keys      : {', '.join(i['key'] for i in issues[:6])}")

    print(f"\n4. Timeline attribution")
    totals, summaries, day_counts, busiest, diag = run(
        client, args.month, board_id, project, wbso, flags
    )
    f = diag.get("funnel", {})
    for label, key in (
        ("candidates fetched", "candidates"),
        ("never In Progress", "never_in_progress"),
        ("in progress outside month", "outside_month"),
        ("no assignee while in progress", "no_assignee_overlap"),
        ("attributed to an engineer", "attributed"),
        ("kept after WBSO filter", "kept_after_wbso_filter"),
        ("excluded as non-WBSO", "excluded_by_wbso_filter"),
    ):
        print(f"   {label:32} {f.get(key, 0)}")

    hours = sum(h for e in totals.values() for t in e.values() for h in t.values())
    print(f"\n5. Result")
    print(f"   engineers        : {len(day_counts)}")
    print(f"   total hours      : {hours:.1f}")

    if not totals:
        unmapped = diag.get("unmapped_epics") or {}
        other = diag.get("wbso_other_team") or {}
        if unmapped:
            print(f"\n   Epics absent from the CSV: {', '.join(sorted(unmapped))}")
        if other:
            print(f"   Epics flagged WBSO under another team: {', '.join(sorted(other))}")
        print("\n   No hours. The stage above where the count reaches 0 is the cause.")
    else:
        print("\n   This team has data — its sheet should be populated.")


if __name__ == "__main__":
    main()
