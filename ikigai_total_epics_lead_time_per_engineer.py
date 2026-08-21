"""
Total Epics Lead Time Per Engineer — Team Ikigai, calendar month.

Identical metric and output to total_epics_lead_time_per_engineer, scoped to
Team Ikigai instead of Pastel de Portal.

The team's Jira project comes from epics-mapping.csv ("Project name" ->
"Project key"), which for Team Ikigai is SPD. Searching board names for
"Ikigai" does not find it — the Jira key bears no resemblance to the team name.
"""

import argparse

from jira_client import from_env
from total_epics_lead_time_per_engineer import DEFAULT_MONTH, print_report, run
from wbso import DEFAULT_CSV, load_mapping

TEAM_NAME = "Team Ikigai"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Total epics lead time per engineer — Team Ikigai.")
    parser.add_argument("--month", default=DEFAULT_MONTH, help="Month as YYYY-MM (default: 2026-07)")
    parser.add_argument("--team", default=TEAM_NAME,
                        help=f"Team name as it appears in the mapping (default: {TEAM_NAME})")
    parser.add_argument("--board", type=int, default=None,
                        help="Board id (default: look up from the team's project)")
    parser.add_argument("--project", default=None,
                        help="Project key (default: read from the mapping CSV)")
    parser.add_argument("--mapping-file", default=DEFAULT_CSV,
                        help=f"Path to the epic mapping CSV (default: {DEFAULT_CSV})")
    args = parser.parse_args()

    if args.project:
        team, project = args.team, args.project
    else:
        team, project = load_mapping(args.mapping_file).project_for_team(args.team)
        print(f"'{args.team}' -> {team}, Jira project {project} (from mapping CSV)")

    client = from_env()

    board_id = args.board
    if board_id is None:
        board_id = client.resolve_board_for_project(project)
    print(f"Using board {board_id} (project {project}).\n")

    totals, summaries = run(client, args.month, board_id, project)
    print_report(totals, summaries, args.month, f"{team} (board {project}/{board_id})")
