"""Authentication + role-based access control.

Demo-grade: credentials come from the Excel ``users`` sheet and are checked
with a constant-time compare. Tokens are signed JWTs carrying role + username.
In production this would be proper password hashing (bcrypt) + a real IdP.
"""

from __future__ import annotations

import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

SECRET_KEY = os.environ.get("CARE_SECRET", "dev-secret-change-me")
ALG = "HS256"
TOKEN_TTL_MIN = int(os.environ.get("CARE_TOKEN_TTL", 720))  # 12h

ROLE_HIERARCHY = {"admin": 3, "nurse": 2, "doctor": 1}

_bearer = HTTPBearer(auto_error=False)


def now() -> str:
    """Department 'wall clock' as HH:MM. Overridable via env for testing."""
    return datetime.now(timezone.utc).astimezone().strftime("%H:%M")


def verify_token(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)):
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing token")
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALG])
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    if "username" not in payload or "role" not in payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "malformed token")
    return payload


def require_role(*roles: str):
    def dep(user: dict = Depends(verify_token)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"role {user['role']} not permitted")
        return user
    return dep


def make_token(username: str, role: str, doctor_id: str = "") -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_TTL_MIN)
    payload = {"username": username, "role": role, "exp": exp}
    if doctor_id:
        payload["doctor_id"] = doctor_id
    return jwt.encode(payload, SECRET_KEY, algorithm=ALG)


def check_password(stored: str, provided: str) -> bool:
    # constant-time compare; stored may be plaintext (demo) or sha256:hex
    if stored.startswith("sha256:"):
        import hashlib
        digest = hashlib.sha256(provided.encode()).hexdigest()
        return hmac.compare_digest(digest, stored[len("sha256:"):])
    return hmac.compare_digest(stored, provided)
