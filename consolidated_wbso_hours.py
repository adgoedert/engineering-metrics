"""
Consolidated WBSO hours -> .xlsx

Same metric and scope as:

    ./run.sh horizon-total-epics-lead-time-per-engineer --board 20 --wbso --month 2025-07

but written to a workbook instead of the terminal. Those three flags are the
defaults here; every one can still be overridden.

The console table is printed as well, so a run is self-verifying: what you see
is what landed in the file.
"""

import argparse
import os

from horizon_total_epics_lead_time_per_engineer import (
    HOURS_PER_DAY,
    TEAM_NAME,
    print_report,
    run,
)
from jira_client import from_env
from wbso import DEFAULT_CSV, load_mapping
from xlsx_export import write_workbook

DEFAULT_MONTH = "2025-07"
DEFAULT_BOARD = 20


def default_output(month: str) -> str:
    return f"consolidated-wbso-hours-{month}.xlsx"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Consolidated WBSO hours per engineer, exported to .xlsx"
    )
    parser.add_argument("--month", default=DEFAULT_MONTH,
                        help=f"Month as YYYY-MM (default: {DEFAULT_MONTH})")
    parser.add_argument("--team", default=TEAM_NAME,
                        help=f"Team name as it appears in the mapping (default: {TEAM_NAME})")
    parser.add_argument("--board", type=int, default=DEFAULT_BOARD,
                        help=f"Board id (default: {DEFAULT_BOARD})")
    parser.add_argument("--project", default=None,
                        help="Project key (default: read from the mapping CSV)")
    parser.add_argument("--wbso-all-teams", action="store_true",
                        help="Accept epics flagged 'yes' under any team, not just this one")
    parser.add_argument("--mapping-file", default=DEFAULT_CSV,
                        help=f"Path to the epic mapping CSV (default: {DEFAULT_CSV})")
    parser.add_argument("--output", default=None,
                        help="Output .xlsx path (default: consolidated-wbso-hours-<month>.xlsx)")
    args = parser.parse_args()

    mapping = load_mapping(args.mapping_file)

    if args.project:
        team, project = args.team, args.project
    else:
        team, project = mapping.project_for_team(args.team)
        print(f"'{args.team}' -> {team}, Jira project {project} (from mapping CSV)")

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
    print(f"Using board {board_id} (project {project}).\n")

    totals, summaries, day_counts, busiest, diagnostics = run(
        client, args.month, board_id, project, wbso_epics, flags
    )

    # Print the same table the terminal report shows, so the export is checkable.
    print_report(
        totals, summaries, day_counts, busiest, args.month,
        f"{team} (board {project}/{board_id})", diagnostics,
    )

    output = args.output or default_output(args.month)
    meta = {
        "hours_per_day": HOURS_PER_DAY,
        "month": args.month,
        "team": team,
        "project": project,
        "board_id": board_id,
        "filter_scope": ("WBSO epics, any team" if args.wbso_all_teams
                         else f"WBSO epics flagged for {team}"),
        "wbso_epic_count": len(wbso_epics),
        "mapping_file": os.path.basename(args.mapping_file),
    }

    path, n_rows = write_workbook(
        output, totals, summaries, day_counts, busiest, diagnostics, meta
    )
    print(f"\nWrote {n_rows} detail row(s) to {path}")
    print("Formulas are written without cached values — open in Excel/LibreOffice")
    print("to populate them, or run scripts/recalc.py if you have LibreOffice.")
