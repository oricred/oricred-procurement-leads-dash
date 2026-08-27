"""Operator commands.

    python -m app.cli create-admin --email ops@oricred.com --name "Ops"
    python -m app.cli backfill-date-source

Replaces the previous behaviour of seeding a fixed administrator account with a
hardcoded password at startup whenever debug was on (see remediation-02 §2.4).
The password is read interactively and never appears in argv, shell history, or
process listings.
"""

import argparse
import asyncio
import getpass
import sys
from datetime import datetime, timezone
from typing import Any

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


async def backfill_date_source(batch_size: int = 5_000) -> None:
    """Populate awards.date_source on rows written before the column existed.

    The nightly repair job scans on this column, so without a backfill the
    first run after deploy would treat every historical award as unresolved.
    Re-runs the resolver against the stored payload rather than guessing.
    """
    from sqlalchemy import select

    from app.jobs.award_check import (
        DATE_SOURCE_SOURCE,
        DATE_SOURCE_SYNTHESISED,
        _resolve_award_date,
    )
    from app.models.award import Award

    total = 0
    while True:
        async with async_session() as db:
            rows = (
                await db.execute(
                    select(Award).where(Award.date_source.is_(None)).limit(batch_size)
                )
            ).scalars().all()
            if not rows:
                break
            now = datetime.now(timezone.utc)
            for award in rows:
                payload: dict[str, Any] = (
                    award.raw_payload if isinstance(award.raw_payload, dict) else {}
                )
                resolved = _resolve_award_date(
                    payload.get("award_date"),
                    award.source_created_at,
                    award.discovered_at,
                    now,
                )
                award.date_source = (
                    DATE_SOURCE_SOURCE if resolved.from_source else DATE_SOURCE_SYNTHESISED
                )
            await db.commit()
            total += len(rows)
            print(f"  {total} awards marked")
        if len(rows) < batch_size:
            break
    print(f"Backfilled date_source on {total} awards")


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

    backfill_parser = sub.add_parser(
        "backfill-date-source", help="Populate awards.date_source on existing rows"
    )
    backfill_parser.add_argument("--batch-size", type=int, default=5_000)

    args = parser.parse_args(argv)

    if args.command == "create-admin":
        if not sys.stdin.isatty():
            raise SystemExit("create-admin needs an interactive terminal to read the password")
        asyncio.run(create_admin(args.email, args.name, _prompt_password()))
    elif args.command == "backfill-date-source":
        asyncio.run(backfill_date_source(args.batch_size))


if __name__ == "__main__":
    main()
