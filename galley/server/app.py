"""Galley accounts, journals, and the archive. Runs beside the desk at /api."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

DATA = Path(os.environ.get("GALLEY_DATA", Path(__file__).resolve().parent / "data"))
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "galley.sqlite"

app = FastAPI(title="Galley")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5174", "http://localhost:5174", "https://galley.drxdhr.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return salt.hex() + ":" + digest.hex()


def check_password(password: str, stored: str) -> bool:
    salt_hex, digest_hex = stored.split(":", 1)
    trial = hash_password(password, bytes.fromhex(salt_hex))
    return trial == stored and digest_hex == trial.split(":", 1)[1]


def init() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              email TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              role TEXT NOT NULL,
              status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
              token TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS journals (
              id TEXT PRIMARY KEY,
              data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS galleys (
              id TEXT PRIMARY KEY,
              owner_id TEXT NOT NULL,
              data TEXT NOT NULL,
              updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            """
        )
        row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        if row["n"] == 0:
            email = os.environ.get("GALLEY_ADMIN_EMAIL", "admin@drxdhr.com")
            password = os.environ.get("GALLEY_ADMIN_PASSWORD", "GalleyAdmin#2026")
            conn.execute(
                "INSERT INTO users (id, name, email, password_hash, role, status) VALUES (?, ?, ?, ?, 'admin', 'approved')",
                ("admin", "Galley admin", email.lower(), hash_password(password)),
            )


init()


class Credentials(BaseModel):
    email: EmailStr
    password: str
    name: str = ""


class StatusChange(BaseModel):
    status: str


class OcrBody(BaseModel):
    dataUrl: str


def user_from_token(authorization: str | None) -> sqlite3.Row:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Sign in required")
    token = authorization.removeprefix("Bearer ").strip()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT users.* FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ?
            """,
            (token,),
        ).fetchone()
    if row is None:
        raise HTTPException(401, "Sign in required")
    if row["status"] != "approved":
        raise HTTPException(403, "This account is not approved")
    return row


def require_admin(authorization: str | None) -> sqlite3.Row:
    user = user_from_token(authorization)
    if user["role"] != "admin":
        raise HTTPException(403, "Only an admin can do that")
    return user


def public_user(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "name": row["name"], "email": row["email"], "role": row["role"], "status": row["status"]}


@app.post("/api/auth/register")
def register(body: Credentials) -> dict:
    if len(body.password) < 8:
        raise HTTPException(400, "Use at least 8 characters for the password")
    user_id = os.urandom(8).hex()
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO users (id, name, email, password_hash, role, status) VALUES (?, ?, ?, ?, 'user', 'pending')",
                (user_id, body.name.strip() or body.email, body.email.lower(), hash_password(body.password)),
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(400, "That email is already registered") from exc
    return {"ok": True, "status": "pending"}


@app.post("/api/auth/login")
def login(body: Credentials) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (body.email.lower(),)).fetchone()
        if row is None or not check_password(body.password, row["password_hash"]):
            raise HTTPException(401, "Email or password is wrong")
        if row["status"] == "pending":
            raise HTTPException(403, "An admin has not approved this account yet")
        if row["status"] == "restricted":
            raise HTTPException(403, "This account is restricted")
        token = os.urandom(24).hex()
        conn.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)", (token, row["id"], int(time.time())))
    return {"token": token, "user": public_user(row)}


@app.get("/api/auth/me")
def me(authorization: str | None = Header(default=None)) -> dict:
    return public_user(user_from_token(authorization))


@app.get("/api/users")
def list_users(authorization: str | None = Header(default=None)) -> list:
    require_admin(authorization)
    with connect() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY name").fetchall()
    return [public_user(row) for row in rows]


@app.post("/api/users")
def add_user(body: Credentials, authorization: str | None = Header(default=None)) -> dict:
    require_admin(authorization)
    if len(body.password) < 8:
        raise HTTPException(400, "Use at least 8 characters for the password")
    user_id = os.urandom(8).hex()
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO users (id, name, email, password_hash, role, status) VALUES (?, ?, ?, ?, 'user', 'approved')",
                (user_id, body.name.strip() or body.email, body.email.lower(), hash_password(body.password)),
            )
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(400, "That email is already registered") from exc
    return public_user(row)


@app.patch("/api/users/{user_id}")
def set_status(user_id: str, body: StatusChange, authorization: str | None = Header(default=None)) -> dict:
    require_admin(authorization)
    if body.status not in {"pending", "approved", "restricted"}:
        raise HTTPException(400, "Unknown status")
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "User not found")
        if row["role"] == "admin" and body.status != "approved":
            raise HTTPException(400, "The admin account stays approved")
        conn.execute("UPDATE users SET status = ? WHERE id = ?", (body.status, user_id))
        if body.status != "approved":
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        updated = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return public_user(updated)


@app.get("/api/settings/open-access")
def get_open_access(authorization: str | None = Header(default=None)) -> dict:
    user_from_token(authorization)
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'openAccess'").fetchone()
    return {"icon": json.loads(row["value"]) if row else None}


@app.put("/api/settings/open-access")
def put_open_access(body: dict = Body(...), authorization: str | None = Header(default=None)) -> dict:
    require_admin(authorization)
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('openAccess', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps(body.get("icon")),),
        )
    return {"ok": True}


@app.get("/api/journals")
def list_journals(authorization: str | None = Header(default=None)) -> list:
    user_from_token(authorization)
    with connect() as conn:
        rows = conn.execute("SELECT data FROM journals").fetchall()
    return [json.loads(row["data"]) for row in rows]


@app.post("/api/journals")
def create_journal(body: dict = Body(...), authorization: str | None = Header(default=None)) -> dict:
    require_admin(authorization)
    journal_id = str(body.get("id") or os.urandom(8).hex())
    body["id"] = journal_id
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO journals (id, data) VALUES (?, ?)", (journal_id, json.dumps(body)))
    return body


@app.delete("/api/journals/{journal_id}")
def delete_journal(journal_id: str, authorization: str | None = Header(default=None)) -> dict:
    require_admin(authorization)
    with connect() as conn:
        conn.execute("DELETE FROM journals WHERE id = ?", (journal_id,))
    return {"ok": True}


@app.get("/api/galleys")
def list_galleys(authorization: str | None = Header(default=None)) -> list:
    user = user_from_token(authorization)
    with connect() as conn:
        if user["role"] == "admin":
            rows = conn.execute(
                """
                SELECT galleys.data, galleys.owner_id, users.name AS owner_name, users.email AS owner_email
                FROM galleys JOIN users ON users.id = galleys.owner_id
                ORDER BY galleys.updated_at DESC
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT galleys.data, galleys.owner_id, users.name AS owner_name, users.email AS owner_email
                FROM galleys JOIN users ON users.id = galleys.owner_id
                WHERE galleys.owner_id = ?
                ORDER BY galleys.updated_at DESC
                """,
                (user["id"],),
            ).fetchall()
    return [
        {
            "galley": json.loads(row["data"]),
            "ownerId": row["owner_id"],
            "ownerName": row["owner_name"],
            "ownerEmail": row["owner_email"],
        }
        for row in rows
    ]


@app.post("/api/galleys")
def create_galley(body: dict = Body(...), authorization: str | None = Header(default=None)) -> dict:
    user = user_from_token(authorization)
    galley_id = str(body.get("id") or os.urandom(8).hex())
    body["id"] = galley_id
    body["updatedAt"] = int(time.time() * 1000)
    with connect() as conn:
        conn.execute(
            "INSERT INTO galleys (id, owner_id, data, updated_at) VALUES (?, ?, ?, ?)",
            (galley_id, user["id"], json.dumps(body), body["updatedAt"]),
        )
    return body


@app.put("/api/galleys/{galley_id}")
def update_galley(galley_id: str, body: dict = Body(...), authorization: str | None = Header(default=None)) -> dict:
    user = user_from_token(authorization)
    body["id"] = galley_id
    body["updatedAt"] = int(time.time() * 1000)
    with connect() as conn:
        row = conn.execute("SELECT owner_id FROM galleys WHERE id = ?", (galley_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Galley not found")
        if user["role"] != "admin" and row["owner_id"] != user["id"]:
            raise HTTPException(403, "You can edit only your own galley")
        conn.execute("UPDATE galleys SET data = ?, updated_at = ? WHERE id = ?", (json.dumps(body), body["updatedAt"], galley_id))
    return body


@app.delete("/api/galleys/{galley_id}")
def delete_galley(galley_id: str, authorization: str | None = Header(default=None)) -> dict:
    require_admin(authorization)
    with connect() as conn:
        conn.execute("DELETE FROM galleys WHERE id = ?", (galley_id,))
    return {"ok": True}


@app.post("/api/ocr")
def ocr(body: OcrBody, authorization: str | None = Header(default=None)) -> dict:
    user_from_token(authorization)
    raw = body.dataUrl.split(",", 1)[-1]
    try:
        image = base64.b64decode(raw)
    except Exception as exc:
        raise HTTPException(400, "That image could not be read") from exc
    suffix = ".png" if "image/png" in body.dataUrl else ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(image)
        path = handle.name
    try:
        result = subprocess.run(
            ["tesseract", path, "stdout", "--psm", "6"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise HTTPException(503, "Equation reading is not available on this computer") from exc
    finally:
        Path(path).unlink(missing_ok=True)
    if result.returncode != 0:
        raise HTTPException(422, result.stderr.strip() or "The equation image could not be read")
    return {"text": result.stdout.strip()}
