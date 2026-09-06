"""Per-platform handle normalisation (Inspiration 2.0, I10; spec §31, §74, §112).

Monitored creators used to be X-only. A creator identity is now
(platform, handle), and every platform has its own rules for what a handle
looks like and how a profile URL is built. Validation stays format-only at
add time (D52): real resolution happens on the first poll, so adding a
creator never blocks on a browser.
"""
from __future__ import annotations

import re

_RULES: dict[str, dict] = {
    "x": {
        "re": re.compile(r"^[A-Za-z0-9_]{1,15}$"),
        "url_re": re.compile(r"^(?:https?://)?(?:www\.)?(?:x\.com|twitter\.com)/(@?[A-Za-z0-9_]{1,15})(?:[/?].*)?$", re.I),
        "profile": "https://x.com/{handle}",
        "reserved": {"home", "explore", "search", "i", "settings", "messages",
                     "notifications", "login"},
        "lower": True,
    },
    "reddit": {
        "re": re.compile(r"^[A-Za-z0-9_-]{3,20}$"),
        "url_re": re.compile(r"^(?:https?://)?(?:www\.|old\.)?reddit\.com/u(?:ser)?/([A-Za-z0-9_-]{3,20})(?:[/?].*)?$", re.I),
        "profile": "https://www.reddit.com/user/{handle}",
        "reserved": {"me", "wiki", "settings"},
        "strip": ("u/", "/u/"),
        "lower": False,
    },
    "bluesky": {
        # handles are domains: name.bsky.social, or a custom domain
        "re": re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$", re.I),
        "url_re": re.compile(r"^(?:https?://)?(?:www\.)?bsky\.app/profile/([^/?]+)(?:[/?].*)?$", re.I),
        "profile": "https://bsky.app/profile/{handle}",
        "reserved": set(),
        "lower": True,
    },
    "youtube": {
        "re": re.compile(r"^[A-Za-z0-9_.-]{3,60}$"),
        "url_re": re.compile(r"^(?:https?://)?(?:www\.)?youtube\.com/@?([A-Za-z0-9_.-]{3,60})(?:[/?].*)?$", re.I),
        "profile": "https://www.youtube.com/@{handle}",
        "reserved": {"watch", "results", "feed", "playlist", "shorts"},
        "lower": False,
    },
    "tiktok": {
        "re": re.compile(r"^[A-Za-z0-9_.]{2,24}$"),
        "url_re": re.compile(r"^(?:https?://)?(?:www\.)?tiktok\.com/@([A-Za-z0-9_.]{2,24})(?:[/?].*)?$", re.I),
        "profile": "https://www.tiktok.com/@{handle}",
        "reserved": {"search", "explore", "foryou"},
        "lower": True,
    },
    "instagram": {
        "re": re.compile(r"^[A-Za-z0-9_.]{1,30}$"),
        "url_re": re.compile(r"^(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9_.]{1,30})(?:[/?].*)?$", re.I),
        "profile": "https://www.instagram.com/{handle}/",
        "reserved": {"explore", "reels", "p", "accounts", "direct"},
        "lower": True,
    },
    "civitai": {
        "re": re.compile(r"^[A-Za-z0-9_.-]{2,40}$"),
        "url_re": re.compile(r"^(?:https?://)?(?:www\.)?civitai\.com/user/([A-Za-z0-9_.-]{2,40})(?:[/?].*)?$", re.I),
        "profile": "https://civitai.com/user/{handle}",
        "reserved": set(),
        "lower": False,
    },
}
DEFAULT_RULE = {
    "re": re.compile(r"^[A-Za-z0-9_.-]{2,60}$"),
    "url_re": None, "profile": None, "reserved": set(), "lower": True,
}

SUPPORTED_PLATFORMS = tuple(_RULES)


def rule(platform: str) -> dict:
    return _RULES.get((platform or "").lower(), DEFAULT_RULE)


def normalize(raw: str, platform: str = "x") -> str | None:
    """'@handle', a bare handle, or a profile URL → canonical handle for that
    platform (or None when it cannot be one)."""
    r = rule(platform)
    raw = (raw or "").strip().rstrip(",;")
    if not raw:
        return None
    if r.get("url_re"):
        m = r["url_re"].match(raw)
        if m:
            raw = m.group(1)
    for prefix in r.get("strip", ()):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix):]
    raw = raw.lstrip("@").strip().strip("/")
    if not raw or not r["re"].match(raw):
        return None
    if r.get("lower", True):
        raw = raw.lower()
    if raw.lower() in r.get("reserved", set()):
        return None
    return raw


def profile_url(handle: str, platform: str = "x") -> str | None:
    tmpl = rule(platform).get("profile")
    return tmpl.format(handle=handle) if tmpl else None


def parse_bulk(text: str, platform: str = "x") -> tuple[list[str], list[str]]:
    """Bulk paste → (valid handles deduped, rejected raw tokens)."""
    valid: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[\s,;]+", text or ""):
        if not token.strip():
            continue
        handle = normalize(token, platform)
        if handle is None:
            rejected.append(token.strip())
        elif handle not in seen:
            seen.add(handle)
            valid.append(handle)
    return valid, rejected


def detect_platform(raw: str) -> str | None:
    """Which platform does this URL belong to? (bulk paste convenience)"""
    for platform, r in _RULES.items():
        if r.get("url_re") and r["url_re"].match((raw or "").strip()):
            return platform
    return None
