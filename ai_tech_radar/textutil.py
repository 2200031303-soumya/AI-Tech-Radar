from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_TAG = re.compile(r"(?is)<(script|style).*?>.*?</\1>")
_HTML = re.compile(r"(?s)<[^>]+>")
_SPACE = re.compile(r"\s+")
_DROP_QUERY = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id", "ref", "source"}


def strip_html(value: str) -> str:
    text = value or ""
    text = _TAG.sub(" ", text)
    text = _HTML.sub(" ", text)
    text = html.unescape(text)
    return _SPACE.sub(" ", text).strip()


def split_sentences(value: str) -> list[str]:
    text = _SPACE.sub(" ", value or "").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'])", text)
    return [part.strip() for part in parts if part.strip()]


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    cleaned = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def within_hours(published: datetime | None, now: datetime, hours: int) -> bool:
    if published is None:
        return False
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    delta = now.astimezone(timezone.utc) - published.astimezone(timezone.utc)
    return delta.total_seconds() >= -300 and delta.total_seconds() <= hours * 3600


def canonical_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    scheme = (parts.scheme or "https").lower()
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    if host.endswith("arxiv.org"):
        host = "arxiv.org"
        scheme = "https"
        path = path.replace("/pdf/", "/abs/")
        path = re.sub(r"\.pdf$", "", path)
        path = re.sub(r"(/abs/\d{4}\.\d+)(v\d+)$", r"\1", path)
        path = re.sub(r"(/abs/[a-z\-]+/\d+)(v\d+)$", r"\1", path)
    query = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=False)
        if key.lower() not in _DROP_QUERY
    ]
    return urlunsplit((scheme, host, path, urlencode(query), ""))


def title_key(title: str) -> str:
    text = (title or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return _SPACE.sub(" ", text).strip()


def contains_term(text: str, term: str) -> bool:
    haystack = (text or "").lower()
    needle = term.lower().strip()
    if not needle:
        return False
    if " " in needle or "-" in needle:
        return needle in haystack
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None
