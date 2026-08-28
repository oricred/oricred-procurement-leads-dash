"""Operator commands.

    python -m app.cli create-admin --email ops@oricred.com --name "Ops"
    python -m app.cli list-users
    python -m app.cli reset-password --email ops@oricred.com [--activate]
    python -m app.cli backfill-date-source
    python -m app.cli audit-orphans [--fix-safe]

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

from sqlalchemy import func, select

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


async def list_users() -> None:
    """Show who can sign in.

    The first thing to check when someone reports that a correct password is
    refused: the address is stored lowercased, and an inactive account is
    refused at login.
    """
    async with async_session() as db:
        users = (await db.execute(select(User).order_by(User.email))).scalars().all()

    if not users:
        print("No users. Create the first one with: python -m app.cli create-admin")
        return

    width = max(len(u.email) for u in users)
    print(f"{'email':<{width}}  {'role':<9}  status")
    for user in users:
        print(f"{user.email:<{width}}  {user.role:<9}  {'active' if user.is_active else 'DISABLED'}")


async def reset_password(email: str, password: str, activate: bool = False) -> None:
    """Set a new password on an existing account.

    `create-admin` refuses to run once any user exists, which left a locked-out
    administrator with no way back in short of editing the database by hand.
    Like create-admin, the password is read interactively and never appears in
    argv, shell history, or a process listing.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

    normalized = email.strip().lower()
    async with async_session() as db:
        # Matched case-insensitively for the same reason login is: a row
        # written before addresses were normalised may be stored mixed-case.
        user = (await db.execute(
            select(User).where(func.lower(User.email) == normalized)
        )).scalars().first()
        if not user:
            raise SystemExit(
                f"No user with address {normalized}. "
                "Run `python -m app.cli list-users` to see the addresses on file."
            )
        user.hashed_password = AuthService.hash_password(password)
        was_disabled = not user.is_active
        if was_disabled and activate:
            user.is_active = True
        await db.commit()
        still_disabled = was_disabled and not activate

    print(f"Password updated for {user.email}")
    if still_disabled:
        print(
            "This account is DISABLED and is refused at login. "
            "Re-run with --activate to enable it."
        )
    elif was_disabled:
        print("Account re-enabled.")


async def backfill_date_source(batch_size: int = 5_000) -> None:
    """Populate awards.date_source on rows written before the column existed.

    The nightly repair job scans on this column, so without a backfill the
    first run after deploy would treat every historical award as unresolved.
    Re-runs the resolver against the stored payload rather than guessing.
    """
    from sqlalchemy import select

    from app.jobs.award_check import _date_provenance, _resolve_award_date
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
                    publication_date=award.publication_date,
                )
                award.date_source = _date_provenance(payload.get("award_date"), resolved)
            await db.commit()
            total += len(rows)
            print(f"  {total} awards marked")
        if len(rows) < batch_size:
            break
    print(f"Backfilled date_source on {total} awards")


# Every relationship in the schema is an unconstrained string column, so these
# can all dangle. Deleting a user leaves opportunities.assigned_to pointing at a
# row that no longer exists; the modal then renders a blank assignee.
#
# (label, child table, child column, parent table, safe automatic repair)
ORPHAN_CHECKS: list[tuple[str, str, str, str, str | None]] = [
    ("opportunity -> tender", "opportunities", "tender_id", "tenders", None),
    ("opportunity -> award", "opportunities", "award_id", "awards", None),
    ("opportunity -> company", "opportunities", "company_id", "companies", None),
    # A departed user should leave the lead unassigned, not dangling.
    ("opportunity -> user", "opportunities", "assigned_to", "users",
     "UPDATE opportunities SET assigned_to = NULL WHERE assigned_to IN "
     "(SELECT o.assigned_to FROM opportunities o LEFT JOIN users u ON u.id = o.assigned_to "
     "WHERE o.assigned_to IS NOT NULL AND u.id IS NULL)"),
    ("award -> tender", "awards", "tender_id", "tenders", None),
    ("contact -> company", "contacts", "company_id", "companies", None),
    ("contact -> organization", "contacts", "organization_id", "organizations", None),
    # Tracking state about a tender is meaningless without the tender.
    ("watchlist -> tender", "watchlist_items", "tender_id", "tenders",
     "DELETE FROM watchlist_items WHERE tender_id NOT IN (SELECT id FROM tenders)"),
    ("past_due -> tender", "past_due_queue", "tender_id", "tenders",
     "DELETE FROM past_due_queue WHERE tender_id NOT IN (SELECT id FROM tenders)"),
]


async def audit_orphans(fix_safe: bool = False) -> None:
    """Report rows whose foreign key points at nothing.

    Run this before adding foreign-key constraints (remediation-07 section 5).
    Constraints cannot be applied while orphans exist, and the orphans that are
    not safely repairable need a decision rather than a delete — an opportunity
    with no tender may still be a real lead someone is working.

    --fix-safe applies only the two unambiguous repairs: unassigning leads whose
    user is gone, and removing watchlist and past-due rows whose tender is gone.
    """
    from sqlalchemy import text

    from app.database import async_session as session_factory

    findings: list[tuple[str, int, bool]] = []
    async with session_factory() as db:
        for label, child, column, parent, safe_fix in ORPHAN_CHECKS:
            count = await db.scalar(text(
                f"SELECT COUNT(*) FROM {child} c "  # noqa: S608 - names are literals above
                f"LEFT JOIN {parent} p ON p.id = c.{column} "
                f"WHERE c.{column} IS NOT NULL AND p.id IS NULL"
            ))
            findings.append((label, int(count or 0), safe_fix is not None))

    width = max(len(label) for label, _, _ in findings)
    total = sum(count for _, count, _ in findings)
    print(f"{'reference':<{width}}  orphans  repairable")
    for label, count, repairable in findings:
        marker = "yes" if repairable else "needs review"
        print(f"{label:<{width}}  {count:>7}  {marker if count else ''}")
    print()

    if total == 0:
        print("No orphans. Foreign-key constraints can be applied safely.")
        return

    unsafe = sum(count for _, count, repairable in findings if count and not repairable)
    if not fix_safe:
        print(f"{total} orphaned rows. Re-run with --fix-safe to apply the safe repairs.")
        if unsafe:
            print(f"{unsafe} of them need a decision, not a delete — see remediation-07 section 5.")
        return

    from sqlalchemy import text as _text

    repaired = 0
    async with session_factory() as db:
        for label, child, column, parent, safe_fix in ORPHAN_CHECKS:
            if not safe_fix:
                continue
            # CursorResult carries rowcount; the Result base class does not.
            affected = getattr(await db.execute(_text(safe_fix)), "rowcount", 0) or 0
            if affected > 0:
                repaired += affected
                print(f"  repaired {affected} rows: {label}")
        await db.commit()
    print(f"Repaired {repaired} rows.")
    if unsafe:
        print(f"{unsafe} orphans remain and need a decision before constraints can be added.")


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

    sub.add_parser("list-users", help="List accounts, their role and whether they are enabled")

    reset_parser = sub.add_parser(
        "reset-password", help="Set a new password on an existing account"
    )
    reset_parser.add_argument("--email", required=True)
    reset_parser.add_argument(
        "--activate", action="store_true", help="Also re-enable a disabled account"
    )

    backfill_parser = sub.add_parser(
        "backfill-date-source", help="Populate awards.date_source on existing rows"
    )
    backfill_parser.add_argument("--batch-size", type=int, default=5_000)

    orphan_parser = sub.add_parser(
        "audit-orphans", help="Report rows whose foreign key points at nothing"
    )
    orphan_parser.add_argument(
        "--fix-safe",
        action="store_true",
        help="Apply only the unambiguous repairs (unassign leads, drop stale tracking rows)",
    )

    args = parser.parse_args(argv)

    if args.command == "create-admin":
        if not sys.stdin.isatty():
            raise SystemExit("create-admin needs an interactive terminal to read the password")
        asyncio.run(create_admin(args.email, args.name, _prompt_password()))
    elif args.command == "list-users":
        asyncio.run(list_users())
    elif args.command == "reset-password":
        if not sys.stdin.isatty():
            raise SystemExit("reset-password needs an interactive terminal to read the password")
        asyncio.run(reset_password(args.email, _prompt_password(), args.activate))
    elif args.command == "backfill-date-source":
        asyncio.run(backfill_date_source(args.batch_size))
    elif args.command == "audit-orphans":
        asyncio.run(audit_orphans(args.fix_safe))


if __name__ == "__main__":
    main()
