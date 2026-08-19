#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python"

# Load .env if it exists
if [[ -f "$SCRIPT_DIR/.env" ]]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

REPORT="${1:-}"

usage() {
  echo ""
  echo "Usage: ./run.sh <report>"
  echo ""
  echo "Available reports:"
  echo "  lead-time                     Lead time for Done tickets in the active sprint (board PT/122)"
  echo "  objectives                    Objective allocation for all tickets in the active sprint (board PT/122)"
  echo "  epics-lead-time-per-engineer  Time per engineer per Epic, active sprint (board PT/122)"
  echo "  total-epics-lead-time-per-engineer"
  echo "                                Time per engineer per Epic per ticket, calendar month"
  echo "                                Pastel de Portal (board PT/122)"
  echo "  ikigai-total-epics-lead-time-per-engineer"
  echo "                                Same report, scoped to Team Ikigai"
  echo "  horizon-total-epics-lead-time-per-engineer"
  echo "                                Team Horizon, capacity model: max 8h/engineer/day"
  echo "                                split equally across tickets held that day"
  echo ""
  echo "Both month reports accept: --month YYYY-MM (default 2026-07)"
  echo "                           --board <id> --project <KEY>  (override auto-detection)"
  echo ""
  echo "Utilities:"
  echo "  boards [name]                 List accessible boards, optionally filtered by name"
  echo ""
}

case "$REPORT" in
  lead-time)
    "$PYTHON" "$SCRIPT_DIR/lead_time.py"
    ;;
  objectives)
    "$PYTHON" "$SCRIPT_DIR/objective_allocation.py"
    ;;
  epics-lead-time-per-engineer)
    "$PYTHON" "$SCRIPT_DIR/epics_lead_time_per_engineer.py"
    ;;
  total-epics-lead-time-per-engineer)
    shift
    "$PYTHON" "$SCRIPT_DIR/total_epics_lead_time_per_engineer.py" "$@"
    ;;
  ikigai-total-epics-lead-time-per-engineer)
    shift
    "$PYTHON" "$SCRIPT_DIR/ikigai_total_epics_lead_time_per_engineer.py" "$@"
    ;;
  horizon-total-epics-lead-time-per-engineer)
    shift
    "$PYTHON" "$SCRIPT_DIR/horizon_total_epics_lead_time_per_engineer.py" "$@"
    ;;
  boards)
    shift
    "$PYTHON" "$SCRIPT_DIR/list_boards.py" "$@"
    ;;
  *)
    echo "❌  Unknown or missing report: '$REPORT'"
    usage
    exit 1
    ;;
esac
