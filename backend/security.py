import json
import re
import secrets
from dataclasses import dataclass
from fastapi import Header, HTTPException
from backend.config import settings


@dataclass(frozen=True)
class Principal:
    id: str
    name: str
    role: str


def authenticate(token: str) -> Principal:
    for expected, identity in json.loads(settings().auth_tokens or "{}").items():
        if secrets.compare_digest(token, expected):
            return Principal(**identity)
    raise HTTPException(401, "Valid bearer token required")


def current_user(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer token required")
    return authenticate(authorization[7:])


def require(user: Principal, *roles):
    if user.role not in roles:
        raise HTTPException(403, "Role is not authorized for this action")


def redact(value):
    if isinstance(value, dict):
        return {
            k: "[REDACTED]"
            if any(s in k.lower() for s in ("secret", "token", "password", "authorization", "email"))
            else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", value)
        return re.sub(r"(?i)(Bearer\s+|sk-)[a-zA-Z0-9_\-]{5,}", "[REDACTED_SECRET]", value)
    return value


def injection_signals(text):
    patterns = [
        r"ignore.{0,35}(instructions|prompt|rules)",
        r"refund every",
        r"不要查规则",
        r"直接退款",
        r"system prompt",
    ]
    return [p for p in patterns if re.search(p, text, re.I)]
