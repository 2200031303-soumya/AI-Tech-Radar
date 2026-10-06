from __future__ import annotations

from datetime import datetime
from urllib.parse import urlencode

from ai_tech_radar.http_client import HttpError, get_bytes
from ai_tech_radar.models import CollectResult, SourceItem
from ai_tech_radar.sources.rss import parse_feed
from ai_tech_radar.textutil import parse_datetime, within_hours


def build_arxiv_url(section: dict) -> str:
    base = (section.get("url") or "https://export.arxiv.org/api/query").strip()
    params = urlencode(
        {
            "search_query": section.get("search_query") or "cat:cs.AI",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": int(section.get("max_results", 15)),
        }
    )
    return base + ("&" if "?" in base else "?") + params


def collect_arxiv(config: dict, now: datetime) -> CollectResult:
    section = config.get("arxiv", {})
    if not section.get("enabled", True):
        return CollectResult("arxiv", [])
    if not (section.get("url") or "").strip():
        return CollectResult("arxiv", [], "arXiv URL is empty. Set arxiv.url in config.json.")
    url = build_arxiv_url(section)
    try:
        payload = get_bytes(url, float(config.get("http_timeout_seconds", 12)), config.get("user_agent", "AI-Tech-Radar/0.1"))
    except (HttpError, OSError) as exc:
        return CollectResult("arxiv", [], str(exc))
    hours = int(config.get("lookback_hours", 36))
    items: list[SourceItem] = []
    for entry in parse_feed(payload):
        published = parse_datetime(entry["published"])
        if not within_hours(published, now, hours):
            continue
        items.append(
            SourceItem(
                source_id="arxiv",
                source_name="arXiv",
                title=entry["title"],
                url=entry["url"],
                published_at=published.isoformat() if published else None,
                excerpt=entry["excerpt"],
                authors=entry["authors"],
                metadata={"priority": 50},
            )
        )
    return CollectResult("arxiv", items)
