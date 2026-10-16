"""Local backup and restore commands. Never submits broker orders."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from nomadquant.config import get_settings
from nomadquant.ops.backup import BackupError, backup_local, restore_local, verify_backup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nomadquant-ops")
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup", help="SQLite-consistent local backup.")
    backup.add_argument("--dest", required=True)
    restore = sub.add_parser("restore", help="Restore only with the backup confirm token.")
    restore.add_argument("--source", required=True)
    restore.add_argument("--confirm", required=True)
    check = sub.add_parser("verify-backup", help="Check a backup without writing live data.")
    check.add_argument("--source", required=True)
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
        if args.command == "backup":
            payload = backup_local(settings, Path(args.dest))
        elif args.command == "restore":
            payload = restore_local(settings, Path(args.source), confirm=args.confirm)
        else:
            payload = verify_backup(Path(args.source))
    except (BackupError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
