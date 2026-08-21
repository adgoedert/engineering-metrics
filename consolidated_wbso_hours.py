"""
Consolidated WBSO hours -> .xlsx, every team in the mapping CSV.

Same metric and capacity model as
horizon_total_epics_lead_time_per_engineer, but run once per team in
epics-mapping.csv and written to a workbook with one sheet per team.

The team list comes from the CSV, so adding or removing a team there changes
this report with no code change.

Each team is processed independently: a team whose board cannot be resolved, or
whose Jira project errors, is recorded on the Summary and Diagnostics sheets and
the run continues. One unreachable project should not cost you every other
team's data.
"""

import argparse
import os
import sys
import traceback

from horizon_total_epics_lead_time_per_engineer import HOURS_PER_DAY, explain_empty, run
from jira_client import from_env
from wbso import DEFAULT_CSV, load_mapping
from xlsx_export import write_workbook

DEFAULT_MONTH = "2025-07"

# Boards pinned per team. A value may be an int (board id) or a str (board
# name, resolved within that team's project). Teams absent from this dict fall
# back to the project's sole board, and error if the project has several.
# Override or extend with --board "Team Name=123" / --board "Team Name=Some board".
DEFAULT_BOARD_OVERRIDES = {
    "Team Horizon": 20,
    "Team Ikigai": 29,
    "Team Samba": 1,
}


def parse_board_overrides(values, base=None):
    """A numeric value is a board id; anything else is a board name."""
    overrides = dict(base or {})
    for item in values or []:
        if "=" not in item:
            raise SystemExit(f"--board expects TEAM=ID or TEAM=NAME, got: {item!r}")
        team, _, board = item.rpartition("=")
        board = board.strip()
        if not team.strip() or not board:
            raise SystemExit(f"--board expects TEAM=ID or TEAM=NAME, got: {item!r}")
        overrides[team.strip()] = int(board) if board.isdigit() else board
    return overrides


def describe_board(pin):
    if pin is None:
        return "resolved from project"
    if isinstance(pin, int):
        return f"id {pin} (pinned)"
    return f"board named {pin!r} (pinned)"


def collect_team(client, mapping, team, project, month, board_pin, all_teams_wbso, flags):
    """
    Run the report for one team. Never raises — failures land in the result.

    board_pin may be an int (use as-is), a str (board name to resolve within the
    project), or None (fall back to the project's sole board).
    """
    scope = None if all_teams_wbso else team
    wbso_epics = mapping.wbso_epics(scope)

    result = {
        "team": team,
        "project": project,
        "month": month,
        "wbso_epic_count": len(wbso_epics),
        "totals": None,
        "summaries": {},
        "day_counts": {},
        "busiest": {},
        "diagnostics": {},
        "status": "",
        "error": "",
        "board_id": board_pin if isinstance(board_pin, int) else None,
        "board_pin": board_pin,
    }

    if not wbso_epics:
        result["status"] = "No epics flagged WBSO for this team in the mapping CSV"
        return result

    board_id = board_pin
    try:
        if isinstance(board_pin, str):
            board_id = client.resolve_board_named(project, board_pin)
        elif board_pin is None:
            board_id = client.resolve_board_for_project(project)
        result["board_id"] = board_id
    except SystemExit as exc:
        result["error"] = str(exc).replace("\n", " ")
        result["status"] = (f"Board {board_pin!r} not found" if isinstance(board_pin, str)
                            else "Board could not be resolved")
        return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["status"] = "Board lookup failed"
        return result

    # A hand-pinned id is easy to get wrong, and a board belonging to another
    # project intersected with "project = X" yields zero issues and an empty
    # sheet. Check it up front and say so, rather than reporting no hours.
    try:
        board_project = client.board_project_key(board_id)
        result["board_project"] = board_project
        if board_project and board_project != project:
            result["status"] = (f"Board {board_id} belongs to project {board_project}, "
                               f"not {project} — no issues can match")
            result["error"] = (f"Pinned board {board_id} is in {board_project}; "
                               f"{team} maps to {project}. Fix the pin in "
                               f"DEFAULT_BOARD_OVERRIDES or pass --board \"{team}=<id>\".")
            return result
    except Exception as exc:
        # Non-fatal: report the mismatch check failed but still try the query.
        result["error"] = f"Board {board_id} check skipped ({type(exc).__name__}: {exc})"

    try:
        totals, summaries, day_counts, busiest, diagnostics = run(
            client, month, board_id, project, wbso_epics, flags
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["status"] = "Jira query failed"
        return result

    result.update({
        "totals": totals,
        "summaries": summaries,
        "day_counts": day_counts,
        "busiest": busiest,
        "diagnostics": diagnostics,
    })
    hours = sum(h for e in totals.values() for t in e.values() for h in t.values())
    result["status"] = (
        f"{hours:.1f}h across {len(day_counts)} engineer(s)" if totals
        else explain_empty(diagnostics)
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Consolidated WBSO hours per engineer for every team, exported to .xlsx"
    )
    parser.add_argument("--month", default=DEFAULT_MONTH,
                        help=f"Month as YYYY-MM (default: {DEFAULT_MONTH})")
    parser.add_argument("--team", action="append", default=None,
                        help="Limit to this team; repeatable. Default: every team in the CSV")
    parser.add_argument("--board", action="append", default=None, metavar="TEAM=ID|NAME",
                        help="Pin a team's board by id or name; repeatable. "
                             f"Defaults: {DEFAULT_BOARD_OVERRIDES}")
    parser.add_argument("--wbso-all-teams", action="store_true",
                        help="Accept epics flagged 'yes' under any team, not just the sheet's own")
    parser.add_argument("--skip-empty-teams", action="store_true",
                        help="Omit sheets for teams with no WBSO epics or no hours")
    parser.add_argument("--mapping-file", default=DEFAULT_CSV,
                        help=f"Path to the epic mapping CSV (default: {DEFAULT_CSV})")
    parser.add_argument("--output", default=None,
                        help="Output .xlsx path (default: consolidated-wbso-hours-<month>.xlsx)")
    args = parser.parse_args()

    mapping = load_mapping(args.mapping_file)
    flags = mapping.flags()
    all_teams = mapping.teams()

    if args.team:
        selected = {}
        for needle in args.team:
            team, project = mapping.project_for_team(needle)
            selected[team] = project
        teams = selected
    else:
        teams = all_teams

    overrides = parse_board_overrides(args.board, DEFAULT_BOARD_OVERRIDES)

    print(f"Consolidated WBSO hours for {args.month}")
    print(f"{len(teams)} team(s) from {os.path.basename(args.mapping_file)}")
    scope_label = ("WBSO epics, any team" if args.wbso_all_teams
                   else "WBSO epics flagged for each team")
    print(f"Epic filter: {scope_label}\n")

    client = from_env()

    results = []
    for i, (team, project) in enumerate(sorted(teams.items()), 1):
        board_pin = overrides.get(team)
        print(f"[{i}/{len(teams)}] {team} ({project}) — {describe_board(board_pin)}")
        res = collect_team(client, mapping, team, project, args.month,
                           board_pin, args.wbso_all_teams, flags)
        resolved = f"board {res['board_id']}, " if res.get("board_id") else ""
        print(f"    -> {resolved}{res['status']}")
        if res["error"]:
            print(f"    !  {res['error'][:160]}", file=sys.stderr)
        results.append(res)

    if args.skip_empty_teams:
        kept = [r for r in results if r.get("totals")]
        dropped = [r["team"] for r in results if not r.get("totals")]
        if dropped:
            print(f"\nOmitting {len(dropped)} team sheet(s) with no hours: {', '.join(dropped)}")
        results = kept

    teams_with_data = sum(1 for r in results if r.get("totals"))
    meta = {
        "hours_per_day": HOURS_PER_DAY,
        "month": args.month,
        "team_count": len(results),
        "teams_with_data": teams_with_data,
        "filter_scope": scope_label,
        "mapping_file": os.path.basename(args.mapping_file),
    }

    output = args.output or f"consolidated-wbso-hours-{args.month}.xlsx"
    path, n_rows, sheet_names = write_workbook(output, results, meta)

    print(f"\nWrote {n_rows} detail row(s) across {len(results)} team sheet(s) to {path}")
    print(f"Teams with WBSO hours: {teams_with_data}/{len(results)}")
    print("Formulas are written without cached values — open the file in Excel or")
    print("LibreOffice once to populate them.")
