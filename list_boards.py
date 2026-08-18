"""List the agile boards you can access, so you can look up ids and project keys."""

import sys

from tabulate import tabulate

from jira_client import from_env

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else None
    client = from_env()

    boards = client.list_boards(name=name)
    if not boards:
        print(f"No boards found{f' matching {name!r}' if name else ''}.")
        sys.exit(0)

    rows = [
        [
            b["id"],
            b.get("name", ""),
            b.get("type", ""),
            b.get("location", {}).get("projectKey", "?"),
        ]
        for b in sorted(boards, key=lambda b: b.get("name", ""))
    ]
    print(tabulate(rows, headers=["Board id", "Name", "Type", "Project"], tablefmt="rounded_outline"))
