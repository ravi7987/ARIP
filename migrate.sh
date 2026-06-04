#!/bin/bash
# migrate.sh — convenience wrapper around common alembic commands.
# Run from the project root: bash migrate.sh <command>
#
# Always run alembic from the project root, never from inside
# the alembic/ directory. The script_location in alembic.ini is
# relative to wherever you invoke alembic from.

set -e  # Exit immediately if any command fails.

CMD=${1:-"help"}

case "$CMD" in
  upgrade)
    echo "Applying all pending migrations..."
    alembic upgrade head
    ;;

  downgrade)
    # Downgrade by N steps. Default: 1 step back.
    STEPS=${2:-"-1"}
    echo "Rolling back $STEPS migration(s)..."
    alembic downgrade "$STEPS"
    ;;

  generate)
    # Auto-generate a new migration from model changes.
    # Usage: bash migrate.sh generate "add email_verified_at to users"
    MSG=${2:-"auto_migration"}
    echo "Generating migration: $MSG"
    alembic revision --autogenerate -m "$MSG"
    echo ""
    echo "Review the generated file in alembic/versions/ before running upgrade."
    ;;

  history)
    alembic history --verbose
    ;;

  current)
    alembic current --verbose
    ;;

  check)
    # Shows pending migrations without applying them.
    echo "Pending migrations (current → head):"
    alembic upgrade head --sql
    ;;

  reset)
    echo "WARNING: This will downgrade ALL the way to base (empty DB)."
    read -p "Are you sure? (yes/no): " confirm
    if [ "$confirm" = "yes" ]; then
      alembic downgrade base
      echo "Database reset to empty state."
    else
      echo "Aborted."
    fi
    ;;

  *)
    echo "Usage: bash migrate.sh <command>"
    echo ""
    echo "Commands:"
    echo "  upgrade              Apply all pending migrations"
    echo "  downgrade [steps]    Roll back N steps (default: 1)"
    echo "  generate \"message\"   Autogenerate migration from model changes"
    echo "  history              Show full migration history"
    echo "  current              Show current DB revision"
    echo "  check                Preview pending SQL without applying"
    echo "  reset                Downgrade all the way to empty DB"
    ;;
esac