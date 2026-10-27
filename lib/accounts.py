"""Accounts, sessions and the synced state.

Passwords are PBKDF2-HMAC-SHA256 with a per-user salt. Session cookies hold a
random token; only its SHA-256 is stored, so a database dump cannot be replayed
as a login. There is no password reset: this is a personal site, not a service
with an inbox.

Registration is "first user only" unless IML_ALLOW_SIGNUP says otherwise, so a
public deployment cannot collect strangers' accounts the moment it is found.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import time

from . import db, sync

USERNAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,31}$")
ITERATIONS = 240_000
SESSION_DAYS = 30
MAX_PASSWORD = 200

# Used to spend the same work on a missing user as on a real one.
_DUMMY = ("00" * 16, "00" * 32, ITERATIONS)


class Unavailable(Exception):
    """The database could not be reached."""


def _store():
    try:
        return db.store()
    except Exception as exc:  # pragma: no cover - configuration problem
        raise Unavailable(str(exc)) from exc


def _hash(password, salt=None, iterations=ITERATIONS):
    salt_bytes = bytes.fromhex(salt) if salt else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 salt_bytes, iterations)
    return salt_bytes.hex(), digest.hex(), iterations


def _matches(password, salt, expected, iterations):
    _, digest, _ = _hash(password, salt, iterations)
    return hmac.compare_digest(digest, expected)


def normalise(username):
    return (username or "").strip().lower()


def signup_mode():
    value = (os.environ.get("IML_ALLOW_SIGNUP") or "first").strip().lower()
    if value in ("1", "true", "yes", "on", "open"):
        return "open"
    if value in ("0", "false", "no", "off", "closed"):
        return "closed"
    return "first"


def has_users():
    try:
        return bool(_store().query("SELECT 1 FROM iml_users LIMIT 1"))
    except Exception as exc:
        raise Unavailable(str(exc)) from exc


def signup_allowed():
    mode = signup_mode()
    if mode == "open":
        return True
    if mode == "closed":
        return False
    return not has_users()


# ------------------------------------------------------------------ throttle


def _throttle(key, limit, window):
    """Count an attempt. Returns (allowed, seconds_to_wait)."""
    now = int(time.time())
    try:
        with _store().tx() as conn:
            rows = conn.run("SELECT n, until FROM iml_throttle WHERE k = %s", (key,))
            if not rows or rows[0][1] < now:
                until = now + window
                conn.run("INSERT INTO iml_throttle (k, n, until) VALUES (%s, 1, %s) "
                         "ON CONFLICT (k) DO UPDATE SET n = 1, until = %s",
                         (key, until, until))
                return True, 0
            count, until = rows[0]
            if count >= limit:
                return False, max(1, until - now)
            conn.run("UPDATE iml_throttle SET n = n + 1 WHERE k = %s", (key,))
            return True, 0
    except Exception as exc:
        raise Unavailable(str(exc)) from exc


def _clear_throttle(key):
    try:
        _store().run("DELETE FROM iml_throttle WHERE k = %s", (key,))
    except Exception:
        pass


# ------------------------------------------------------------------- accounts


def register(username, password, ip=""):
    display = (username or "").strip()
    name = normalise(display)
    if not USERNAME.match(name):
        return None, ("Use 3 to 32 characters: letters, numbers, dot, dash "
                      "or underscore."), 400
    if len(password or "") < 8:
        return None, "Use at least 8 characters for the password.", 400
    if len(password or "") > MAX_PASSWORD:
        return None, "That password is too long.", 400

    allowed, wait = _throttle("reg:" + (ip or "?"), 5, 3600)
    if not allowed:
        return None, ("Too many accounts from here. Try again in %d minutes."
                      % max(1, wait // 60)), 429

    salt, digest, iterations = _hash(password)
    now = int(time.time())

    try:
        with _store().tx() as conn:
            if conn.dialect == "postgres":
                # Serialise "is this the first user?" across instances.
                conn.run("SELECT pg_advisory_xact_lock(%s)", (453921,))
            mode = signup_mode()
            if mode == "closed":
                return None, "Registration is closed on this site.", 403
            if mode == "first":
                count = conn.run("SELECT COUNT(*) FROM iml_users")[0][0]
                if count:
                    return None, "Registration is closed on this site.", 403
            if conn.run("SELECT 1 FROM iml_users WHERE username = %s", (name,)):
                return None, "That username is taken.", 409

            conn.run("INSERT INTO iml_users "
                     "(username, display, salt, hash, iterations, created) "
                     "VALUES (%s, %s, %s, %s, %s, %s)",
                     (name, display[:32], salt, digest, iterations, now))
            conn.run("INSERT INTO iml_state (username, rev, updated, state) "
                     "VALUES (%s, 0, %s, %s)", (name, now, "{}"))
    except Unavailable:
        raise
    except Exception as exc:
        raise Unavailable(str(exc)) from exc

    _clear_throttle("reg:" + (ip or "?"))
    return {"username": name, "display": display[:32]}, "", 201


def login(username, password, ip=""):
    name = normalise(username)
    key = "login:" + (ip or "?")
    allowed, wait = _throttle(key, 8, 600)
    if not allowed:
        return None, ("Too many attempts. Try again in %d minutes."
                      % max(1, wait // 60)), 429
    if not name or not password:
        return None, "Enter a username and password.", 400

    try:
        rows = _store().query(
            "SELECT username, display, salt, hash, iterations "
            "FROM iml_users WHERE username = %s", (name,))
    except Unavailable:
        raise
    except Exception as exc:
        raise Unavailable(str(exc)) from exc

    if not rows:
        _matches(password, *_DUMMY)  # same cost as a real check
        return None, "Wrong username or password.", 401

    stored, display, salt, digest, iterations = rows[0]
    if not _matches(password, salt, digest, int(iterations)):
        return None, "Wrong username or password.", 401

    _clear_throttle(key)
    return {"username": stored, "display": display}, "", 200


# ------------------------------------------------------------------- sessions


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(username):
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with _store().tx() as conn:
        conn.run("DELETE FROM iml_sessions WHERE expires < %s", (now,))
        conn.run("INSERT INTO iml_sessions (token, username, expires) "
                 "VALUES (%s, %s, %s)",
                 (_token_hash(token), username, now + SESSION_DAYS * 86400))
    return token


def user_for_token(token):
    if not token or len(token) > 200:
        return None
    try:
        rows = _store().query(
            "SELECT u.username, u.display, s.expires "
            "FROM iml_sessions s JOIN iml_users u ON u.username = s.username "
            "WHERE s.token = %s", (_token_hash(token),))
    except Exception:
        return None
    if not rows:
        return None
    username, display, expires = rows[0]
    if int(expires) < int(time.time()):
        delete_session(token)
        return None
    return {"username": username, "display": display}


def delete_session(token):
    if not token:
        return
    try:
        _store().run("DELETE FROM iml_sessions WHERE token = %s",
                     (_token_hash(token),))
    except Exception:
        pass


# ---------------------------------------------------------------------- state


def empty_state():
    return sync.empty()


def load_state(username):
    try:
        rows = _store().query(
            "SELECT rev, updated, state FROM iml_state WHERE username = %s",
            (username,))
    except Exception as exc:
        raise Unavailable(str(exc)) from exc
    if not rows:
        return empty_state(), 0, 0
    rev, updated, raw = rows[0]
    return sync.load(raw), int(rev), int(updated or 0)


def save_state(username, incoming):
    now = int(time.time())
    lock = " FOR UPDATE" if _store().dialect == "postgres" else ""
    try:
        with _store().tx() as conn:
            rows = conn.run(
                "SELECT rev, updated, state FROM iml_state WHERE username = %s"
                + lock, (username,))
            if rows:
                rev, updated, raw = rows[0]
                server = sync.load(raw)
            else:
                rev, updated, server = 0, 0, {}

            merged = sync.merge(server, incoming)
            payload = sync.encoded(merged)
            if len(payload.encode("utf-8")) > sync.MAX_STATE:
                raise ValueError("too large")

            new_rev = int(rev) + 1
            if rows:
                conn.run("UPDATE iml_state SET rev = %s, updated = %s, "
                         "state = %s WHERE username = %s",
                         (new_rev, now, payload, username))
            else:
                conn.run("INSERT INTO iml_state "
                         "(username, rev, updated, state) VALUES (%s, %s, %s, %s)",
                         (username, new_rev, now, payload))
    except ValueError:
        raise
    except Exception as exc:
        raise Unavailable(str(exc)) from exc
    return merged, new_rev, now


def clear_state(username):
    now = int(time.time())
    payload = sync.encoded(sync.empty())
    try:
        with _store().tx() as conn:
            rows = conn.run("SELECT rev FROM iml_state WHERE username = %s"
                            + (" FOR UPDATE" if conn.dialect == "postgres" else ""),
                            (username,))
            rev = int(rows[0][0]) + 1 if rows else 1
            if rows:
                conn.run("UPDATE iml_state SET rev = %s, updated = %s, "
                         "state = %s WHERE username = %s",
                         (rev, now, payload, username))
            else:
                conn.run("INSERT INTO iml_state "
                         "(username, rev, updated, state) VALUES (%s, %s, %s, %s)",
                         (username, rev, now, payload))
    except Exception as exc:
        raise Unavailable(str(exc)) from exc
    return sync.empty(), rev, now


def state_summary(username):
    try:
        state, _rev, _updated = load_state(username)
    except Unavailable:
        return {"saved": 0, "watching": 0}
    return sync.summary(state)
