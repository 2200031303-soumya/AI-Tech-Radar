from __future__ import annotations

import os
from datetime import datetime, timezone
from urllib.parse import urlencode

from ai_tech_radar.http_client import HttpError, get_bytes, get_json
from ai_tech_radar.models import CollectResult, SourceItem
from ai_tech_radar.sources.rss import parse_feed
from ai_tech_radar.textutil import parse_datetime, within_hours


def github_headers(config: dict) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token_env = config.get("github", {}).get("token_env", "GITHUB_TOKEN")
    token = os.getenv(token_env, "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def build_repo_search_url(config: dict, since_date: str) -> str:
    github = config.get("github", {})
    base = github.get("api_base", "https://api.github.com").rstrip("/") + "/search/repositories"
    query = github.get("search_query") or "llm"
    min_stars = int(github.get("min_stars", 50))
    q = f"created:>={since_date} stars:>={min_stars} ({query})"
    return base + "?" + urlencode(
        {
            "q": q,
            "sort": "stars",
            "order": "desc",
            "per_page": int(github.get("search_per_page", 10)),
        }
    )


def repos_from_search(payload) -> list[SourceItem]:
    items: list[SourceItem] = []
    rows = payload.get("items", []) if isinstance(payload, dict) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        full_name = str(row.get("full_name") or "")
        url = str(row.get("html_url") or "")
        description = str(row.get("description") or "").strip()
        if not full_name or not url:
            continue
        topics = row.get("topics") or []
        topic_text = ", ".join(str(topic) for topic in topics[:8])
        excerpt = description
        if topic_text:
            excerpt = (excerpt + f" Topics: {topic_text}.").strip()
        license_info = row.get("license") or {}
        license_name = license_info.get("spdx_id") if isinstance(license_info, dict) else None
        items.append(
            SourceItem(
                source_id="github-search",
                source_name="GitHub",
                title=full_name,
                url=url,
                published_at=str(row.get("created_at") or row.get("pushed_at") or ""),
                excerpt=excerpt or full_name,
                authors=[full_name.split("/")[0]] if "/" in full_name else [],
                metadata={
                    "priority": 60,
                    "stars": row.get("stargazers_count"),
                    "language": row.get("language"),
                    "license": license_name,
                    "release": None,
                },
            )
        )
    return items


def collect_github_search(config: dict, now: datetime) -> CollectResult:
    github = config.get("github", {})
    if not github.get("api_base"):
        return CollectResult(
            "github-search",
            [],
            "GitHub API base is empty. Set github.api_base in config.json.",
        )
    since = (now.astimezone(timezone.utc)).date().isoformat()
    hours = int(config.get("lookback_hours", 36))
    if hours > 24:
        since = (now.astimezone(timezone.utc) - _hours(hours)).date().isoformat()
    url = build_repo_search_url(config, since)
    try:
        payload = get_json(
            url,
            float(config.get("http_timeout_seconds", 12)),
            config.get("user_agent", "AI-Tech-Radar/0.1"),
            github_headers(config),
        )
    except (HttpError, OSError, ValueError) as exc:
        return CollectResult("github-search", [], str(exc))
    kept: list[SourceItem] = []
    for item in repos_from_search(payload):
        published = parse_datetime(item.published_at)
        if published is not None and not within_hours(published, now, hours):
            continue
        if published is not None:
            item.published_at = published.isoformat()
        kept.append(item)
    return CollectResult("github-search", kept)


def collect_github_releases(config: dict, now: datetime) -> CollectResult:
    repos = config.get("github", {}).get("watch_releases") or []
    if not repos:
        return CollectResult(
            "github-releases",
            [],
            "No repositories are configured. Add github.watch_releases in config.json.",
        )
    timeout = float(config.get("http_timeout_seconds", 12))
    user_agent = config.get("user_agent", "AI-Tech-Radar/0.1")
    hours = int(config.get("lookback_hours", 36))
    items: list[SourceItem] = []
    errors: list[str] = []
    for repo in repos:
        url = f"https://github.com/{repo}/releases.atom"
        try:
            payload = get_bytes(url, timeout, user_agent)
            entries = parse_feed(payload)
        except (HttpError, OSError) as exc:
            errors.append(f"{repo}: {exc}")
            continue
        for entry in entries[:5]:
            published = parse_datetime(entry["published"])
            if not within_hours(published, now, hours):
                continue
            author = repo.split("/")[0]
            items.append(
                SourceItem(
                    source_id="github-releases",
                    source_name=f"GitHub Releases ({repo})",
                    title=entry["title"],
                    url=entry["url"],
                    published_at=published.isoformat() if published else None,
                    excerpt=entry["excerpt"] or entry["title"],
                    authors=[author],
                    metadata={"priority": 70, "repo": repo, "release": entry["title"]},
                )
            )
    error = "; ".join(errors) if errors else None
    return CollectResult("github-releases", items, error)


def _hours(hours: int):
    from datetime import timedelta

    return timedelta(hours=hours)
