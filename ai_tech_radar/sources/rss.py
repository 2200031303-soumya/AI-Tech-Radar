from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from ai_tech_radar.http_client import HttpError, get_bytes
from ai_tech_radar.models import CollectResult, SourceItem
from ai_tech_radar.textutil import parse_datetime, strip_html, within_hours


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(element) if _local(child.tag) == name]


def _text(element: ET.Element, names: tuple[str, ...]) -> str:
    for name in names:
        for child in _children(element, name):
            value = "".join(child.itertext()).strip()
            if value:
                return value
    return ""


def _link(element: ET.Element) -> str:
    for child in _children(element, "link"):
        href = child.attrib.get("href", "").strip()
        rel = child.attrib.get("rel", "alternate")
        text = "".join(child.itertext()).strip()
        if href and rel in {"", "alternate"}:
            return href
        if text.startswith("http"):
            return text
    return ""


def _authors(element: ET.Element) -> list[str]:
    names: list[str] = []
    for child in list(element):
        local = _local(child.tag)
        if local in {"author", "creator"}:
            person = _text(child, ("name",)) or "".join(child.itertext()).strip()
            if person and person not in names:
                names.append(strip_html(person))
    return names


def parse_feed(xml_bytes: bytes) -> list[dict]:
    """Parse RSS 2.0 and Atom documents into plain item dictionaries."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    items = [element for element in root.iter() if _local(element.tag) in {"item", "entry"}]
    parsed: list[dict] = []
    for item in items:
        title = strip_html(_text(item, ("title",)))
        url = _link(item)
        excerpt = strip_html(_text(item, ("description", "summary", "content", "encoded")))
        published = _text(item, ("published", "updated", "pubDate", "date"))
        if title and url:
            parsed.append(
                {
                    "title": title,
                    "url": url,
                    "excerpt": excerpt,
                    "published": published,
                    "authors": _authors(item),
                }
            )
    return parsed


def collect_rss_feeds(config: dict, now: datetime) -> CollectResult:
    items: list[SourceItem] = []
    errors: list[str] = []
    timeout = float(config.get("http_timeout_seconds", 12))
    user_agent = config.get("user_agent", "AI-Tech-Radar/0.1")
    hours = int(config.get("lookback_hours", 36))
    for feed in config.get("rss_feeds", []):
        if not feed.get("enabled", True):
            continue
        url = (feed.get("url") or "").strip()
        feed_id = feed.get("id") or feed.get("name") or "rss"
        if not url:
            errors.append(f"{feed_id}: feed URL is empty. Set rss_feeds[].url in config.json to enable it.")
            continue
        try:
            payload = get_bytes(url, timeout, user_agent)
            entries = parse_feed(payload)
        except HttpError as exc:
            errors.append(f"{feed_id}: {exc}")
            continue
        except OSError as exc:
            errors.append(f"{feed_id}: {exc}")
            continue
        kept = 0
        for entry in entries:
            published = parse_datetime(entry["published"])
            if not within_hours(published, now, hours):
                continue
            items.append(
                SourceItem(
                    source_id=feed_id,
                    source_name=feed.get("name") or feed_id,
                    title=entry["title"],
                    url=entry["url"],
                    published_at=published.astimezone(timezone.utc).isoformat() if published else None,
                    excerpt=entry["excerpt"],
                    authors=entry["authors"],
                    metadata={
                        "priority": int(feed.get("priority", 50)),
                        "require_ai_terms": bool(feed.get("require_ai_terms", False)),
                    },
                )
            )
            kept += 1
            if kept >= 20:
                break
    error = "; ".join(errors) if errors else None
    return CollectResult("rss", items, error)
