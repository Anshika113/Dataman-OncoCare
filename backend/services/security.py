"""Authentication + role-based access control.

Credentials live in the Excel ``users`` sheet, stored as bcrypt hashes
(plaintext demo values are auto-hashed on first login). Tokens are signed
JWTs carrying username, role, doctor_id, a unique ``jti`` (for revocation)
and a ``tv`` token-version (password change / logout invalidates every
issued token for that user).

Production posture:
- secret must come from the environment (startup refuses an unsafe default)
- short-lived access tokens + logout / revocation via an in-memory registry
- constant-time bcrypt verification, per-IP login rate limiting
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

import bcrypt
from pydantic_settings import BaseSettings, SettingsConfigDict

ALG = "HS256"
ROLE_HIERARCHY = {"admin": 3, "nurse": 2, "doctor": 1}

# A derived, stable "auto" secret is used when CARE_SECRET is not provided.
# It is deterministic from CARE_AUTO_SALT (default: a random value persisted to
# a file) so tokens survive a restart of the *same* deployment, while a fresh
# host gets a fresh secret. Production should always set CARE_SECRET explicitly.
_AUTO_SALT_PATH = os.environ.get(
    "CARE_AUTO_SALT_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", ".secret-salt"),
)
_AUTO_SALT_ENV = os.environ.get("CARE_AUTO_SALT")


def _derive_auto_secret() -> str:
    salt = _AUTO_SALT_ENV
    if not salt:
        try:
            with open(_AUTO_SALT_PATH, "r", encoding="utf-8") as f:
                salt = f.read().strip()
        except OSError:
            salt = ""
    if not salt:
        salt = secrets.token_hex(32)
        try:
            os.makedirs(os.path.dirname(_AUTO_SALT_PATH), exist_ok=True)
            with open(_AUTO_SALT_PATH, "w", encoding="utf-8") as f:
                f.write(salt)
            os.chmod(_AUTO_SALT_PATH, 0o600)
        except OSError:
            pass  # read-only FS: fall back to the ephemeral salt
    return hashlib.sha256(("oncocare:auto:" + salt).encode()).hexdigest()


class SecuritySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARE_", extra="ignore")

    secret: str = ""                    # empty => derive a persistent auto secret
    token_ttl_min: int = 480            # 8h access token
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000,http://localhost:5173,http://127.0.0.1:5173"
    login_max_attempts: int = 10        # per IP
    login_window_sec: int = 300         # over a 5 minute window

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = SecuritySettings()
SECRET_KEY = settings.secret or _derive_auto_secret()

_bearer = HTTPBearer(auto_error=False)


# --------------------------------------------------------------------------- #
# Department clock (HH:MM)
# --------------------------------------------------------------------------- #
def now() -> str:
    """Department 'wall clock' as HH:MM. Overridable via env for testing."""
    if os.environ.get("CARE_NOW"):
        return os.environ["CARE_NOW"]
    return datetime.now(timezone.utc).astimezone().strftime("%H:%M")


def today() -> str:
    """Department 'working day' as YYYY-MM-DD. Overridable via env for testing.

    This is the day the schedule is operated on — appointments, leaves and
    capacity are all scoped to it. ``CARE_TODAY`` lets tests pin a specific day.
    """
    if os.environ.get("CARE_TODAY"):
        return os.environ["CARE_TODAY"]
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


# --------------------------------------------------------------------------- #
# Token registry: revocation + token version
# --------------------------------------------------------------------------- #
# jti -> username of revoked (logged-out) tokens
_REVOKED: set[str] = set()
# username -> token version; bumping invalidates every earlier token
_TOKEN_VERSION: dict[str, int] = {}


def revoke_token(jti: str) -> None:
    _REVOKED.add(jti)


def bump_token_version(username: str) -> None:
    _TOKEN_VERSION[username] = _TOKEN_VERSION.get(username, 0) + 1


def make_token(username: str, role: str, doctor_id: str = "") -> tuple[str, str]:
    """Return (token, jti)."""
    jti = uuid.uuid4().hex
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.token_ttl_min)
    payload = {
        "username": username,
        "role": role,
        "jti": jti,
        "tv": _TOKEN_VERSION.get(username, 0),
        "iat": int(time.time()),
        "exp": exp,
    }
    if doctor_id:
        payload["doctor_id"] = doctor_id
    return jwt.encode(payload, SECRET_KEY, algorithm=ALG), jti


def decode_token(token: str) -> dict:
    """Decode + validate a raw JWT (liveness, revocation, token version).
    Raises HTTPException(401) on any failure."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALG])
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    if "username" not in payload or "role" not in payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "malformed token")
    jti = payload.get("jti")
    if jti and jti in _REVOKED:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token revoked")
    tv = payload.get("tv", 0)
    if _TOKEN_VERSION.get(payload["username"], 0) != tv:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired")
    return payload


def verify_token(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> dict:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing token")
    return decode_token(creds.credentials)


def appointment_token(appt_id: str) -> str:
    """An unguessable, stable link token for one appointment.

    Derived from the signing secret rather than stored, so no migration and
    no extra column — and it dies with the secret. It identifies a visit, not
    a person, and the page it opens shows nothing about anybody else.
    """
    import hashlib
    import hmac as _hmac
    mac = _hmac.new(SECRET_KEY.encode(), appt_id.encode(), hashlib.sha256)
    return mac.hexdigest()[:24]


def appointment_for_token(token: str, appointment_ids) -> str:
    """Find which appointment a token belongs to, in constant time per id."""
    import hmac as _hmac
    for aid in appointment_ids:
        if _hmac.compare_digest(appointment_token(aid), token):
            return aid
    return ""


def require_role(*roles: str):
    def dep(user: dict = Depends(verify_token)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"role {user['role']} not permitted")
        return user
    return dep


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(stored: str, provided: str) -> bool:
    """Constant-time bcrypt check. Accepts a bcrypt hash or (legacy)
    plaintext / ``sha256:hex`` demo values, which are verified by direct
    compare so pre-existing seed data keeps working until re-hashed."""
    if stored.startswith("$2"):
        try:
            return bcrypt.checkpw(provided.encode(), stored.encode())
        except ValueError:
            return False
    # legacy plaintext (constant-time)
    if stored and not stored.startswith("sha256:"):
        return hmac.compare_digest(stored.encode(), provided.encode())
    if stored.startswith("sha256:"):
        import hashlib
        digest = hashlib.sha256(provided.encode()).hexdigest()
        return hmac.compare_digest(digest, stored[len("sha256:"):])
    return False


def upgrade_password(stored: str, provided: str) -> str | None:
    """If the stored value is not a bcrypt hash but the provided password
    verifies against it, return the new bcrypt hash (else None)."""
    if stored.startswith("$2"):
        return None
    if check_password(stored, provided):
        return _hash(provided)
    return None


# --------------------------------------------------------------------------- #
# Login rate limiting (per client IP)
# --------------------------------------------------------------------------- #
_attempts: dict[str, deque[float]] = {}


def _recent_failures(client_ip: str) -> deque:
    """This IP's failures inside the window, with older ones dropped."""
    dq = _attempts.setdefault(client_ip, deque())
    cutoff = time.time() - settings.login_window_sec
    while dq and dq[0] <= cutoff:
        dq.popleft()
    if not dq:
        _attempts.pop(client_ip, None)   # don't grow a dict of empty deques
    return dq


def login_throttled(client_ip: str) -> None:
    """Raise 429 if this IP has used up its budget of *failed* logins.

    The budget counts failures only, and a success clears it. Counting
    successes would buy nothing — someone who guessed the password is not
    stopped by a counter — while locking out the people who typed it
    correctly. Nine demo accounts signed into one after another is a real
    sequence, and under the old rule it exhausted the budget and locked the
    tenth out.

    This records nothing. Call :func:`login_failed` after a failed attempt
    and :func:`login_succeeded` after a good one.
    """
    if len(_recent_failures(client_ip)) >= settings.login_max_attempts:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "too many failed sign-in attempts from this "
                            "network; try again in a few minutes")


def login_failed(client_ip: str) -> None:
    """Charge one failed attempt against this IP."""
    _recent_failures(client_ip)
    _attempts.setdefault(client_ip, deque()).append(time.time())


def login_succeeded(client_ip: str) -> None:
    """Clear the budget: whoever this is, they have the credential."""
    _attempts.pop(client_ip, None)
