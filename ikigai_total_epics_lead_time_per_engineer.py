"""
Total Epics Lead Time Per Engineer — Team Ikigai, calendar month.

Identical metric and output to total_epics_lead_time_per_engineer, scoped to
Team Ikigai instead of Pastel de Portal. The board id and project key are not
hardcoded: they are resolved at runtime by searching board names for "Ikigai",
so this works without anyone having to look the id up first.

Override with --board / --project if the name search is ambiguous.
"""

import argparse

from jira_client import from_env
from total_epics_lead_time_per_engineer import DEFAULT_MONTH, print_report, run

TEAM_NAME = "Ikigai"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Total epics lead time per engineer — Team Ikigai.")
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

    totals, summaries = run(client, args.month, board_id, project)
    print_report(totals, summaries, args.month, f"Team {TEAM_NAME} (board {project}/{board_id})")
