"""Diagnose a rejected login against whatever database this environment points at.

    cd backend && .venv/bin/python scripts/diagnose_login.py
    cd backend && .venv/bin/python scripts/diagnose_login.py --email ops@oricred.com
    cd backend && .venv/bin/python scripts/diagnose_login.py --email ops@oricred.com --check-password
    cd backend && .venv/bin/python scripts/diagnose_login.py --token

STRICTLY READ-ONLY. It issues SELECTs against the Oricred database and does not
write, commit, or alter anything. Run it on the host that serves the API, with
the same environment the API process has, so that it reads the same database and
the same ORICRED_JWT_SECRET.

It separates the three failures that all surface to the user as one message:

  1. the address on file does not match what is typed (case or a stray space),
  2. the password does not match the stored hash,
  3. the credentials are fine and the *token* is rejected afterwards — a
     disabled account, an expired token, a reverse proxy dropping the
     Authorization header, or two API instances signing with different secrets.

No password, hash, or secret is ever printed.
"""

import argparse
import asyncio
import getpass
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlsplit

from jose import JWTError, jwt
from sqlalchemy import func, select

from app.config import settings
from app.database import async_session
from app.models.user import User
from app.services.auth import AuthService


def _describe_database() -> str:
    """Host and database name only — never the password."""
    parts = urlsplit(settings.database_url)
    host = parts.hostname or "(local file)"
    port = f":{parts.port}" if parts.port else ""
    name = (parts.path or "").lstrip("/") or "(none)"
    return f"{parts.scheme} -> {host}{port}/{name}"


def _secret_fingerprint() -> str:
    """A stable, non-reversible tag for the signing key.

    Run this on each API instance: if the fingerprints differ, a token minted by
    one is rejected by the next, and the user is bounced to the login screen at
    random depending on which instance the load balancer picked.
    """
    if not settings.jwt_secret:
        return "UNSET — the app cannot verify any token"
    return f"{hashlib.sha256(settings.jwt_secret.encode()).hexdigest()[:12]} (len {len(settings.jwt_secret)})"


async def show_accounts(email: str | None) -> list[User]:
    async with async_session() as db:
        if email:
            normalized = email.strip().lower()
            rows = (await db.execute(
                select(User).where(func.lower(User.email) == normalized)
            )).scalars().all()
            if not rows:
                print(f"No account matches {normalized!r}, even case-insensitively.")
                every = (await db.execute(select(User).order_by(User.email))).scalars().all()
                print(f"{len(every)} account(s) on file:")
                for user in every:
                    print(f"  {user.email!r}")
                return []
        else:
            rows = (await db.execute(select(User).order_by(User.email))).scalars().all()

    if not rows:
        print("This database has no users at all. Nobody can sign in.")
        print("Create the first one with: python -m app.cli create-admin")
        return []

    print(f"{len(rows)} account(s):")
    for user in rows:
        # repr() so a trailing space or a capital letter is visible rather than
        # invisible — that difference alone rejected a correct password.
        flags = []
        if not user.is_active:
            flags.append("DISABLED — refused at login")
        if user.email != user.email.strip().lower():
            flags.append("NOT NORMALISED — stored with case or whitespace")
        if not str(user.hashed_password or "").startswith("$2"):
            flags.append("HASH IS NOT BCRYPT — no password can ever verify")
        print(f"  email    {user.email!r}")
        print(f"  id       {user.id}")
        print(f"  role     {user.role}")
        print(f"  active   {user.is_active}")
        print(f"  hash     {str(user.hashed_password or '')[:4]}... len {len(user.hashed_password or '')}")
        for flag in flags:
            print(f"  !! {flag}")
        print()
    return rows


async def check_password(email: str) -> None:
    """Verify a typed password against the stored hash. Reads only."""
    password = getpass.getpass("Password to test (not echoed, not stored): ")
    async with async_session() as db:
        user = await AuthService.authenticate(db, email, password)
    if user:
        print(f"MATCH — these credentials are valid for {user.email}.")
        print("So the rejection happens after login. Run --token next.")
    else:
        print("NO MATCH against the stored hash.")
        print("Either the password is wrong, or the account is disabled (see 'active' above).")
        print("Reset it with: python -m app.cli reset-password --email <address> [--activate]")


async def check_token() -> None:
    """Explain why a token the browser is holding gets refused.

    Copy it from the browser: DevTools -> Application -> Local Storage -> token.
    """
    token = getpass.getpass("Paste the token from localStorage (not echoed): ").strip()
    if not token:
        print("Nothing pasted.")
        return

    # AuthService.decode_token() returns {} for any JWTError, which folds "the
    # signature is wrong" together with "this expired an hour ago" — the right
    # call for the API, which refuses both, but useless for telling them apart
    # here. Verify the signature with expiry checking off, then report the
    # expiry separately below.
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False},
        )
    except JWTError as exc:
        print("This token does NOT verify against this process's ORICRED_JWT_SECRET.")
        print(f"  reason: {exc}")
        print("Either the secret changed since the token was issued (a rotation breaks")
        print("every existing session; signing in again fixes those), or a different")
        print("instance signed it. Compare the fingerprint above across every API")
        print("instance — they must be identical.")
        return

    print("Signature is valid against this process's secret.")
    exp = payload.get("exp")
    if exp:
        expires = datetime.fromtimestamp(exp, tz=timezone.utc)
        remaining = expires - datetime.now(timezone.utc)
        state = "EXPIRED" if remaining.total_seconds() <= 0 else "valid"
        print(f"  expires  {expires.isoformat()} ({state}, {remaining})")
        if remaining.total_seconds() <= 0:
            print("  !! EXPIRED. It is refused and the app returns to the login page.")
            print("     Signing in again issues a fresh one. If it expired sooner than")
            print(f"     ORICRED_JWT_EXPIRE_MINUTES ({settings.jwt_expire_minutes}m) should")
            print("     allow, this host's clock is likely wrong — compare `date -u` here")
            print("     with the browser's clock.")
            return

    subject = payload.get("sub")
    print(f"  subject  {subject}")
    async with async_session() as db:
        user = await AuthService.get_user(db, str(subject))
    if not user:
        print("  !! No user with that id in THIS database. The token was minted against")
        print("     a different database than the one this environment points at.")
    elif not user.is_active:
        print(f"  !! {user.email} is DISABLED. Every request is refused after login.")
        print("     Re-enable with: python -m app.cli reset-password --email "
              f"{user.email} --activate")
    else:
        print(f"  resolves to {user.email} ({user.role}), active.")
        print()
        print("This token is entirely valid. If the browser is still being logged out,")
        print("the token is not reaching the API — check that the reverse proxy forwards")
        print("the Authorization header. Confirm from outside the host:")
        print('  curl -sS -o /dev/null -w "%{http_code}\\n" \\')
        print('       -H "Authorization: Bearer $TOKEN" https://<your-host>/api/auth/me')
        print("401 there but 200 against the API directly means the proxy strips it.")


async def main(args: argparse.Namespace) -> None:
    print(f"database        {_describe_database()}")
    print(f"jwt secret      {_secret_fingerprint()}")
    print(f"token lifetime  {settings.jwt_expire_minutes} minutes")
    print(f"debug           {settings.debug}")
    print()

    users = await show_accounts(args.email)
    if args.check_password:
        if not args.email:
            raise SystemExit("--check-password needs --email")
        if not users:
            return
        await check_password(args.email)
    if args.token:
        print()
        await check_token()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", help="Limit to one address (matched case-insensitively)")
    parser.add_argument("--check-password", action="store_true",
                        help="Prompt for a password and verify it against the stored hash")
    parser.add_argument("--token", action="store_true",
                        help="Prompt for a token from the browser and explain why it is refused")
    asyncio.run(main(parser.parse_args()))
