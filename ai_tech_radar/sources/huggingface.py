from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlencode

from ai_tech_radar.http_client import HttpError, get_json
from ai_tech_radar.models import CollectResult, SourceItem
from ai_tech_radar.textutil import parse_datetime, strip_html, within_hours


def _as_list(payload) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("papers", "items", "dailyPapers", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _author_names(paper: dict) -> list[str]:
    authors = paper.get("authors") or []
    names: list[str] = []
    if isinstance(authors, list):
        for author in authors:
            if isinstance(author, str) and author.strip():
                names.append(author.strip())
            elif isinstance(author, dict):
                name = author.get("name") or author.get("fullname") or ""
                if name:
                    names.append(str(name).strip())
    return names


def papers_from_payload(payload, *, min_upvotes: int) -> list[SourceItem]:
    items: list[SourceItem] = []
    for row in _as_list(payload):
        if not isinstance(row, dict):
            continue
        paper = row.get("paper") if isinstance(row.get("paper"), dict) else row
        title = strip_html(str(paper.get("title") or "")).strip()
        paper_id = str(paper.get("id") or paper.get("paperId") or "").strip()
        url = str(paper.get("url") or "")
        if not url and paper_id:
            url = f"https://huggingface.co/papers/{paper_id}"
        excerpt = strip_html(str(paper.get("summary") or paper.get("abstract") or ""))
        upvotes = row.get("upvotes", paper.get("upvotes", row.get("numUpvotes", 0)))
        try:
            upvotes_value = int(upvotes or 0)
        except (TypeError, ValueError):
            upvotes_value = 0
        if upvotes_value < min_upvotes:
            continue
        published_raw = str(row.get("publishedAt") or paper.get("publishedAt") or paper.get("published") or "")
        if not title or not url:
            continue
        items.append(
            SourceItem(
                source_id="huggingface-papers",
                source_name="Hugging Face Daily Papers",
                title=title,
                url=url,
                published_at=published_raw or None,
                excerpt=excerpt,
                authors=_author_names(paper),
                metadata={"priority": 75, "upvotes": upvotes_value, "paper_id": paper_id},
            )
        )
    return items


def collect_huggingface_papers(config: dict, now: datetime) -> CollectResult:
    section = config.get("huggingface_papers", {})
    if not section.get("enabled", True):
        return CollectResult("huggingface-papers", [])
    base = (section.get("url") or "").strip()
    if not base:
        return CollectResult(
            "huggingface-papers",
            [],
            "Hugging Face papers URL is empty. Set huggingface_papers.url in config.json.",
        )
    params = urlencode({"limit": int(section.get("limit", 15))})
    url = base + ("&" if "?" in base else "?") + params
    try:
        payload = get_json(url, float(config.get("http_timeout_seconds", 12)), config.get("user_agent", "AI-Tech-Radar/0.1"))
    except (HttpError, OSError, ValueError) as exc:
        return CollectResult("huggingface-papers", [], str(exc))
    hours = int(config.get("lookback_hours", 36))
    min_upvotes = int(section.get("min_upvotes", 0))
    kept: list[SourceItem] = []
    for item in papers_from_payload(payload, min_upvotes=min_upvotes):
        published = parse_datetime(item.published_at)
        if published is not None and not within_hours(published, now, hours):
            continue
        if published is not None:
            item.published_at = published.astimezone(timezone.utc).isoformat()
        kept.append(item)
    return CollectResult("huggingface-papers", kept)
