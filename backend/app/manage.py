"""Small admin CLI.

Usage (from the repo root):

    python -m backend.app.manage create-user you@example.com --role admin
    python -m backend.app.manage list-users
"""
import argparse
import getpass
import sys

from fastapi import HTTPException

from .auth import create_user, list_users


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="manage", description="Soil Boring Ops admin commands")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-user", help="Create a user (prompts for the password)")
    create.add_argument("email")
    create.add_argument("--role", choices=["admin", "manager", "general", "lab", "finance"], default="general")

    sub.add_parser("list-users", help="List existing users")

    args = parser.parse_args(argv)

    if args.command == "list-users":
        for user in list_users():
            print(f"{user['email']}\t{user['role']}")
        return 0

    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.", file=sys.stderr)
        return 1
    try:
        created = create_user(args.email, password, args.role)
    except HTTPException as exc:
        print(f"Error: {exc.detail}", file=sys.stderr)
        return 1
    print(f"Created {created['role']} account for {created['email']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
