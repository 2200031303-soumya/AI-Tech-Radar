from __future__ import annotations

import re

from ai_tech_radar.http_client import HttpError, get_json
from ai_tech_radar.models import SourceItem
from ai_tech_radar.sources.github import github_headers


_REPO = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")


def enrich_items(items: list[SourceItem], config: dict, *, offline: bool) -> list[str]:
    """Attach GitHub star counts when the source link points at a repository.

    Star counts are read from the GitHub API and stored on the item. The model
    is not asked to invent them. Failures are recorded and the item is kept.
    """
    if offline:
        return []
    github = config.get("github", {})
    api_base = (github.get("api_base") or "").rstrip("/")
    if not api_base:
        return ["GitHub enrichment skipped: github.api_base is empty."]
    errors: list[str] = []
    timeout = float(config.get("http_timeout_seconds", 12))
    user_agent = config.get("user_agent", "AI-Tech-Radar/0.1")
    headers = github_headers(config)
    for item in items:
        if item.metadata.get("stars") is not None:
            continue
        match = _REPO.search(item.url or "")
        if not match:
            continue
        owner, repo = match.group(1), match.group(2)
        if repo.endswith(".git"):
            repo = repo[:-4]
        url = f"{api_base}/repos/{owner}/{repo}"
        try:
            payload = get_json(url, timeout, user_agent, headers)
        except (HttpError, OSError, ValueError) as exc:
            errors.append(f"{owner}/{repo}: {exc}")
            continue
        if not isinstance(payload, dict):
            continue
        stars = payload.get("stargazers_count")
        if isinstance(stars, int):
            item.metadata["stars"] = stars
        license_info = payload.get("license") or {}
        if isinstance(license_info, dict) and license_info.get("spdx_id"):
            item.metadata["license"] = license_info["spdx_id"]
        description = payload.get("description")
        if description and len(item.excerpt or "") < 40:
            item.excerpt = str(description)
    return errors
