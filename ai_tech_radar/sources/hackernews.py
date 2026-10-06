from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from ai_tech_radar.http_client import HttpError, get_json
from ai_tech_radar.models import CollectResult, SourceItem
from ai_tech_radar.textutil import strip_html


def build_hn_url(config: dict, now: datetime) -> str:
    section = config.get("hackernews", {})
    base = (section.get("url") or "https://hn.algolia.com/api/v1/search_by_date").strip()
    hours = int(config.get("lookback_hours", 36))
    since = int((now.astimezone(timezone.utc) - timedelta(hours=hours)).timestamp())
    min_points = int(section.get("min_points", 40))
    params = urlencode(
        {
            "query": section.get("query") or "AI",
            "tags": "story",
            "numericFilters": f"points>{min_points},created_at_i>{since}",
            "hitsPerPage": int(section.get("hits_per_page", 20)),
        }
    )
    return base + ("&" if "?" in base else "?") + params


def stories_from_payload(payload) -> list[SourceItem]:
    hits = payload.get("hits", []) if isinstance(payload, dict) else []
    items: list[SourceItem] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        title = strip_html(str(hit.get("title") or "")).strip()
        object_id = str(hit.get("objectID") or "")
        url = str(hit.get("url") or "")
        if not url and object_id:
            url = f"https://news.ycombinator.com/item?id={object_id}"
        if not title or not url:
            continue
        story_text = strip_html(str(hit.get("story_text") or ""))
        points = hit.get("points") or 0
        try:
            points_value = int(points)
        except (TypeError, ValueError):
            points_value = 0
        comments = hit.get("num_comments") or 0
        excerpt = story_text or title
        if points_value:
            excerpt = f"{excerpt} Hacker News points: {points_value}. Comments: {comments}."
        items.append(
            SourceItem(
                source_id="hackernews",
                source_name="Hacker News",
                title=title,
                url=url,
                published_at=str(hit.get("created_at") or ""),
                excerpt=excerpt,
                authors=[str(hit.get("author"))] if hit.get("author") else [],
                metadata={
                    "priority": 40,
                    "points": points_value,
                    "comments": comments,
                    "require_ai_terms": True,
                    "hn_url": f"https://news.ycombinator.com/item?id={object_id}" if object_id else "",
                },
            )
        )
    return items


def collect_hackernews(config: dict, now: datetime) -> CollectResult:
    section = config.get("hackernews", {})
    if not section.get("enabled", True):
        return CollectResult("hackernews", [])
    if not (section.get("url") or "").strip():
        return CollectResult("hackernews", [], "Hacker News URL is empty. Set hackernews.url in config.json.")
    url = build_hn_url(config, now)
    try:
        payload = get_json(url, float(config.get("http_timeout_seconds", 12)), config.get("user_agent", "AI-Tech-Radar/0.1"))
    except (HttpError, OSError, ValueError) as exc:
        return CollectResult("hackernews", [], str(exc))
    return CollectResult("hackernews", stories_from_payload(payload))
