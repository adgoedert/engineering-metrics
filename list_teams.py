"""List the team -> Jira project mappings held in epics-mapping.csv."""

from tabulate import tabulate

from wbso import load_mapping

if __name__ == "__main__":
    mapping = load_mapping()
    teams = mapping.teams()

    rows = []
    for team, project in sorted(teams.items()):
        epics = [r for r in mapping.rows if r["team"] == team]
        rows.append([
            team,
            project,
            len(epics),
            len(mapping.wbso_epics(team)),
        ])

    print(tabulate(
        rows,
        headers=["Team (Project name)", "Jira key", "Epics", "WBSO epics"],
        tablefmt="rounded_outline",
    ))
    print(f"\nUse the left-hand name with --team, e.g. --team \"Team Horizon\"")
