from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Sequence
import uuid

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, Field

from app.config import get_settings


security_bearer = HTTPBearer(auto_error=False)


class Role(str, Enum):
    CUSTOMER = "customer"
    SUPPORT = "support"
    SUPERVISOR = "supervisor"
    ADMIN = "admin"
    AUDITOR = "auditor"


class TokenPayload(BaseModel):
    sub: str  # User ID or subject
    email: str | None = None
    role: Role = Role.CUSTOMER
    exp: datetime
    iat: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AuthenticatedUser(BaseModel):
    id: uuid.UUID
    email: str | None = None
    role: Role
    is_active: bool = True


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its bcrypt hash."""
    try:
        pwd_bytes = plain_password.encode("utf-8")
        hash_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(pwd_bytes, hash_bytes)
    except Exception:
        return False


def create_access_token(
    subject: str | uuid.UUID,
    role: Role | str = Role.CUSTOMER,
    email: str | None = None,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Generate a signed JWT access token."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    role_str = role.value if isinstance(role, Role) else str(role)
    to_encode = {
        "sub": str(subject),
        "email": email,
        "role": role_str,
        "iat": now,
        "exp": expire,
    }
    if extra_claims:
        to_encode.update(extra_claims)

    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    return encoded_jwt


def decode_access_token(token: str) -> TokenPayload:
    """Decode and validate a JWT access token."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        sub: str = payload.get("sub")
        if sub is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing subject claim",
                headers={"WWW-Authenticate": "Bearer"},
            )
        role_str = payload.get("role", Role.CUSTOMER.value)
        try:
            role = Role(role_str)
        except ValueError:
            role = Role.CUSTOMER

        return TokenPayload(
            sub=sub,
            email=payload.get("email"),
            role=role,
            exp=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
            iat=datetime.fromtimestamp(payload.get("iat", datetime.now(timezone.utc).timestamp()), tz=timezone.utc),
        )
    except JWTError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate credentials: {str(err)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_bearer),
) -> AuthenticatedUser:
    """FastAPI dependency to extract and authenticate the current user from Bearer token."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    payload = decode_access_token(token)
    try:
        user_uuid = uuid.UUID(payload.sub)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identifier format in token",
        )

    return AuthenticatedUser(
        id=user_uuid,
        email=payload.email,
        role=payload.role,
        is_active=True,
    )


def require_roles(*allowed_roles: Role | str) -> Callable:
    """RBAC Dependency factory enforcing one of the specified roles."""
    normalized_roles = [
        r.value if isinstance(r, Role) else str(r)
        for r in allowed_roles
    ]

    async def role_checker(
        current_user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        if current_user.role.value not in normalized_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted. Required roles: {normalized_roles}",
            )
        return current_user

    return role_checker
