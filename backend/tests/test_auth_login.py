"""Regression guard for login rejecting valid credentials.

`AuthService.authenticate` matched `User.email` against the raw form input,
while every write path (`cli.create_admin`, `_bootstrap_admin`, the admin Users
API) stores `email.strip().lower()`. A browser that autocapitalised the address
or autofilled it with a trailing space therefore got "Invalid credentials" with
a correct password.

It also issued a token to a deactivated account, which `get_current_user` then
refused on the next request — the user landed on the dashboard and was bounced
straight back to the login screen.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.user import User
from app.services.auth import AuthService

PASSWORD = "correct horse battery staple"


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


async def _add_user(db: AsyncSession, email: str, *, is_active: bool = True) -> User:
    user = User(
        id=str(uuid.uuid4()),
        email=email,
        name="Ops",
        hashed_password=AuthService.hash_password(PASSWORD),
        role="admin",
        is_active=is_active,
    )
    db.add(user)
    await db.commit()
    return user


@pytest.mark.asyncio
@pytest.mark.parametrize("typed", [
    "ops@oricred.com",
    "Ops@Oricred.com",
    "OPS@ORICRED.COM",
    "  ops@oricred.com",
    "ops@oricred.com ",
    " Ops@Oricred.com ",
])
async def test_a_stored_address_is_matched_however_it_was_typed(db, typed):
    await _add_user(db, "ops@oricred.com")
    user = await AuthService.authenticate(db, typed, PASSWORD)
    assert user is not None, f"{typed!r} was rejected with the correct password"
    assert user.email == "ops@oricred.com"


@pytest.mark.asyncio
async def test_a_row_stored_before_normalisation_still_authenticates(db):
    """Rows written by hand or by an older build may be mixed-case."""
    await _add_user(db, "Ops@Oricred.com")
    assert await AuthService.authenticate(db, "ops@oricred.com", PASSWORD) is not None


@pytest.mark.asyncio
async def test_the_wrong_password_is_still_refused(db):
    await _add_user(db, "ops@oricred.com")
    assert await AuthService.authenticate(db, "ops@oricred.com", "not the password") is None


@pytest.mark.asyncio
async def test_an_unknown_address_is_refused(db):
    await _add_user(db, "ops@oricred.com")
    assert await AuthService.authenticate(db, "nobody@oricred.com", PASSWORD) is None


@pytest.mark.asyncio
async def test_a_deactivated_account_is_refused_at_login(db):
    """Not handed a token that every subsequent request rejects."""
    await _add_user(db, "gone@oricred.com", is_active=False)
    assert await AuthService.authenticate(db, "gone@oricred.com", PASSWORD) is None


@pytest.mark.asyncio
async def test_two_rows_differing_only_by_case_resolve_to_the_normalised_one(db):
    await _add_user(db, "Ops@Oricred.com")
    await _add_user(db, "ops@oricred.com")
    user = await AuthService.authenticate(db, "OPS@ORICRED.COM", PASSWORD)
    assert user is not None
    assert user.email == "ops@oricred.com"
