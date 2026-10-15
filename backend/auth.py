"""Local accounts: salted PBKDF2 password hashes and cookie sessions."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, HTTPException

from db import STARTING_CASH, connect

SESSION_COOKIE = "pta_session"
SESSION_DAYS = 30
_ITERATIONS = 200_000


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS).hex()


def _now():
    return datetime.now(timezone.utc)


def create_user(username: str, password: str) -> int:
    username = username.strip()
    if not (3 <= len(username) <= 30) or not username.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Username must be 3-30 letters, numbers, - or _.")
    if len(password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters.")
    salt = secrets.token_hex(16)
    with connect() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            raise HTTPException(409, "That username is taken.")
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, salt, starting_cash, cash) VALUES (?, ?, ?, ?, ?)",
            (username, _hash(password, salt), salt, STARTING_CASH, STARTING_CASH),
        )
        return cur.lastrowid


def verify_user(username: str, password: str) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, password_hash, salt FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
    if not row or not hmac.compare_digest(row["password_hash"], _hash(password, row["salt"])):
        raise HTTPException(401, "Wrong username or password.")
    return row["id"]


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = (_now() + timedelta(days=SESSION_DAYS)).isoformat()
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_now().isoformat(),))
        conn.execute("INSERT INTO sessions VALUES (?, ?, ?)", (token, user_id, expires))
    return token


def delete_session(token: str):
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def current_user(pta_session: str | None = Cookie(default=None)) -> dict:
    """FastAPI dependency: the logged-in user, or 401."""
    if not pta_session:
        raise HTTPException(401, "Not logged in.")
    with connect() as conn:
        row = conn.execute(
            """SELECT u.id, u.username, u.cash, u.starting_cash, u.created_at, s.expires_at
               FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?""",
            (pta_session,),
        ).fetchone()
    if not row or row["expires_at"] < _now().isoformat():
        raise HTTPException(401, "Session expired.")
    return dict(row)
