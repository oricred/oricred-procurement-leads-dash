from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    @staticmethod
    def hash_password(password: str) -> str:
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(plain: str, hashed: str) -> bool:
        return pwd_context.verify(plain, hashed)

    @staticmethod
    def create_token(user_id: str, role: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
        payload = {"sub": user_id, "role": role, "exp": expire}
        return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    @staticmethod
    def decode_token(token: str) -> dict:
        try:
            return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        except JWTError:
            return {}

    @staticmethod
    async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
        """Look the user up the way every write path stores them.

        `cli.create_admin`, `_bootstrap_admin` and the admin Users API all
        write `email.strip().lower()`. Login compared the raw form input
        against that, so an address the browser autocapitalised or autofilled
        with a trailing space was rejected with a correct password. Match
        case-insensitively as well, in case a row predating that normalisation
        is still stored mixed-case.

        An account that has been deactivated is refused here rather than being
        handed a token that `get_current_user` rejects on the next request —
        that bounced the user straight back to the login screen.
        """
        normalized = email.strip().lower()
        result = await db.execute(
            select(User).where(func.lower(User.email) == normalized).limit(2)
        )
        candidates = result.scalars().all()
        # Two rows differing only by case is an ambiguity we do not resolve
        # silently; only an exact match on the normalised address counts.
        if len(candidates) == 1:
            user = candidates[0]
        else:
            user = next((u for u in candidates if u.email == normalized), None)
        if user and user.is_active and AuthService.verify_password(password, user.hashed_password):
            return user
        return None

    @staticmethod
    async def get_user(db: AsyncSession, user_id: str) -> User | None:
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
