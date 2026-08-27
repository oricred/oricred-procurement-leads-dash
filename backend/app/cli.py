"""Operator commands.

    python -m app.cli create-admin --email ops@oricred.com --name "Ops"

Replaces the previous behaviour of seeding a fixed administrator account with a
hardcoded password at startup whenever debug was on (see remediation-02 §2.4).
The password is read interactively and never appears in argv, shell history, or
process listings.
"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.database import async_session, init_db
from app.models.user import User
from app.services.auth import AuthService

MIN_PASSWORD_LENGTH = 12


async def create_admin(email: str, name: str, password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

    email = email.strip().lower()
    if not email or "@" not in email:
        raise SystemExit("A valid email address is required")

    await init_db()
    async with async_session() as db:
        if (await db.execute(select(User).limit(1))).first():
            raise SystemExit(
                "A user already exists. Use Admin -> Users in the app to add more."
            )
        db.add(User(
            email=email,
            name=name.strip() or "Administrator",
            hashed_password=AuthService.hash_password(password),
            role="admin",
        ))
        await db.commit()
    print(f"Created administrator {email}")


def _prompt_password() -> str:
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords do not match")
    return password


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    admin_parser = sub.add_parser("create-admin", help="Create the first administrator")
    admin_parser.add_argument("--email", required=True)
    admin_parser.add_argument("--name", default="Administrator")

    args = parser.parse_args(argv)

    if args.command == "create-admin":
        if not sys.stdin.isatty():
            raise SystemExit("create-admin needs an interactive terminal to read the password")
        asyncio.run(create_admin(args.email, args.name, _prompt_password()))


if __name__ == "__main__":
    main()
