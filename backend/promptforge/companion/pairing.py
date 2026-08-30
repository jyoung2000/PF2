"""Companion pairing (9.1, D42): 6-digit single-use codes with 10-min TTL →
stored bearer tokens (sha256 at rest). Revoking deletes the row and closes any
live socket."""
from __future__ import annotations

import hashlib
import secrets
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Companion

CODE_TTL_S = 10 * 60

_active_codes: dict[str, float] = {}  # code -> expiry monotonic ts


class PairingError(Exception):
    pass


def issue_code() -> dict:
    # prune expired
    now = time.time()
    for code in [c for c, exp in _active_codes.items() if exp < now]:
        _active_codes.pop(code, None)
    code = f"{secrets.randbelow(1_000_000):06d}"
    _active_codes[code] = now + CODE_TTL_S
    return {"code": code, "expires_in_s": CODE_TTL_S}


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def pair(s: Session, code: str, name: str) -> dict:
    exp = _active_codes.get(code)
    if exp is None or exp < time.time():
        raise PairingError(
            "Pairing code invalid or expired — generate a fresh one in "
            "Settings → Companion (codes last 10 minutes, single use).")
    _active_codes.pop(code, None)  # single-use
    token = "pfc_" + secrets.token_hex(16)
    companion = Companion(name=(name or "Desktop")[:100],
                          token_sha256=hash_token(token))
    s.add(companion)
    s.flush()
    return {"token": token, "companion_id": companion.id,
            "name": companion.name}


def authenticate(s: Session, token: str) -> Companion | None:
    if not token or not token.startswith("pfc_"):
        return None
    return s.execute(select(Companion).where(
        Companion.token_sha256 == hash_token(token))).scalar_one_or_none()


def revoke(s: Session, companion_id: int) -> bool:
    companion = s.get(Companion, companion_id)
    if companion is None:
        return False
    s.delete(companion)
    s.flush()
    return True
