"""
Authentication — JWT-based with roles: admin | user

Setup:
  1. Set AUTH_SECRET_KEY in .env (run: python -c "import secrets; print(secrets.token_hex(32))")
  2. Set ADMIN_USERNAME / ADMIN_PASSWORD / USER_USERNAME / USER_PASSWORD in .env
     (for a full multi-user system, replace with a users DB or Google Sheet)
"""

import os
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "change-me-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRE_MINUTES", 480))  # 8 hours

# ── Password hashing context ────────────────────────────────────────────────
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# bcrypt and some pbkdf2 implementations enforce 72-byte limit
# We truncate explicitly to avoid errors
MAX_PASSWORD_BYTES = 72

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ── Simple in-process user store (replace with DB for production) ───────────
# Passwords are stored hashed.

USERS_DB: dict[str, dict] = {}

def _truncate_password(password: str) -> str:
    """Safely truncate password to max 72 bytes (utf-8 encoded)."""
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > MAX_PASSWORD_BYTES:
        password_bytes = password_bytes[:MAX_PASSWORD_BYTES]
        # Decode back (ignore errors in case of bad byte boundary)
        return password_bytes.decode("utf-8", errors="ignore")
    return password


def _load_users():
    """Load users from environment variables with safe password truncation."""
    users = {}

    admin_u = os.getenv("ADMIN_USERNAME", "admin")
    admin_p = os.getenv("ADMIN_PASSWORD", "admin123")
    user_u  = os.getenv("USER_USERNAME", "user")
    user_p  = os.getenv("USER_PASSWORD", "user123")

    if admin_p:
        truncated_pw = _truncate_password(admin_p)
        users[admin_u] = {
            "username": admin_u,
            "hashed_password": pwd_context.hash(truncated_pw),
            "role": "admin",
        }

    if user_p:
        truncated_pw = _truncate_password(user_p)
        users[user_u] = {
            "username": user_u,
            "hashed_password": pwd_context.hash(truncated_pw),
            "role": "user",
        }

    return users


USERS_DB = _load_users()


# ── Models ────────────────────────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str
    role: str
    username: str

class TokenData(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password after safe truncation."""
    truncated = _truncate_password(plain_password)
    return pwd_context.verify(truncated, hashed_password)


def authenticate_user(username: str, password: str) -> Optional[dict]:
    user = USERS_DB.get(username)
    if not user or not verify_password(password, user["hashed_password"]):
        return None
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# ── Dependencies ──────────────────────────────────────────────────────────────

async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        if username is None:
            raise credentials_exception
        return {"username": username, "role": role}
    except JWTError:
        raise credentials_exception


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def require_any_role(current_user: dict = Depends(get_current_user)) -> dict:
    """Any authenticated user (admin or user)."""
    return current_user