"""
The epic mapping in epics-mapping.csv.

The CSV carries two things this tool needs:

  1. Which Jira project belongs to which team. The "Project name" column holds
     the human team name ("Team Horizon") and "Project key" the Jira key
     ("SUK") — these do not resemble each other, so the CSV is the only
     reliable way to get from one to the other.
  2. Which epics are flagged for WBSO.

It is maintained by hand outside this tool, so the loader is strict about the
columns it needs and loud about rows it cannot use: a silently dropped epic
shows up as missing hours, which is far harder to notice than an error.
"""

import csv
import os

DEFAULT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "epics-mapping.csv")

EPIC_KEY_COLUMN = "Parent key"
WBSO_COLUMN = "WBSO yes/no"
TEAM_COLUMN = "Project name"
PROJECT_KEY_COLUMN = "Project key"

REQUIRED_COLUMNS = (EPIC_KEY_COLUMN, WBSO_COLUMN, TEAM_COLUMN, PROJECT_KEY_COLUMN)


class EpicMapping:
    """Queryable view over the CSV rows."""

    def __init__(self, rows: list[dict]):
        self.rows = rows

    # -- teams -------------------------------------------------------------

    def teams(self) -> dict:
        """{team name: project key}, first key seen wins."""
        out = {}
        for row in self.rows:
            if row["team"] and row["project_key"]:
                out.setdefault(row["team"], row["project_key"])
        return out

    def resolve_team(self, needle: str) -> str:
        """
        Match a team name case-insensitively, allowing a substring ("Horizon"
        finds "Team Horizon"). Raises with the full list when ambiguous.
        """
        teams = self.teams()
        needle_l = needle.strip().lower()

        exact = [t for t in teams if t.lower() == needle_l]
        if exact:
            return exact[0]

        partial = [t for t in teams if needle_l in t.lower()]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            raise SystemExit(
                f"'{needle}' matches {len(partial)} teams: {', '.join(sorted(partial))}\n"
                f"Pass the full name, or --project to bypass the lookup."
            )
        listing = "\n".join(f"  {t}  ->  {k}" for t, k in sorted(teams.items()))
        raise SystemExit(
            f"No team matching '{needle}' in the epic mapping.\nKnown teams:\n{listing}"
        )

    def project_for_team(self, needle: str) -> tuple[str, str]:
        """Return (canonical_team_name, project_key)."""
        team = self.resolve_team(needle)
        return team, self.teams()[team]

    # -- WBSO --------------------------------------------------------------

    def wbso_epics(self, team: str = None) -> set:
        """Epic keys flagged 'yes', optionally restricted to one team's rows."""
        return {
            r["epic_key"]
            for r in self.rows
            if r["flag"] == "yes" and (team is None or r["team"] == team)
        }

    def flags(self) -> dict:
        """{epic key: flag} across every team, for 'is this epic mapped at all'."""
        return {r["epic_key"]: r["flag"] for r in self.rows}

    def teams_of_epic(self, epic_key: str) -> set:
        return {r["team"] for r in self.rows if r["epic_key"] == epic_key and r["team"]}

    def summarise(self, team: str = None) -> str:
        epics = self.wbso_epics(team)
        by_project = {}
        for key in epics:
            prefix = key.split("-")[0]
            by_project[prefix] = by_project.get(prefix, 0) + 1
        breakdown = ", ".join(f"{p}: {n}" for p, n in sorted(by_project.items()))
        scope = f"for {team}" if team else "across all teams"
        return f"{len(epics)} WBSO epics {scope} ({breakdown})" if epics else f"no WBSO epics {scope}"


def load_mapping(path: str = DEFAULT_CSV) -> EpicMapping:
    if not os.path.exists(path):
        raise SystemExit(
            f"Epic mapping not found: {path}\n"
            f"Expected a CSV with columns: {', '.join(REQUIRED_COLUMNS)}"
        )

    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(
                f"{path} is missing required column(s): {', '.join(missing)}\n"
                f"Found: {', '.join(reader.fieldnames or [])}"
            )

        rows = []
        blank_keys = 0
        for raw in reader:
            epic_key = (raw.get(EPIC_KEY_COLUMN) or "").strip()
            if not epic_key:
                blank_keys += 1
                continue
            rows.append({
                "epic_key": epic_key,
                "flag": (raw.get(WBSO_COLUMN) or "").strip().lower(),
                "team": (raw.get(TEAM_COLUMN) or "").strip(),
                "project_key": (raw.get(PROJECT_KEY_COLUMN) or "").strip(),
            })

    if blank_keys:
        print(f"Note: skipped {blank_keys} row(s) in {os.path.basename(path)} with no epic key.")

    return EpicMapping(rows)
