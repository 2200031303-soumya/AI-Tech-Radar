from __future__ import annotations

from ai_tech_radar.models import CollectResult
from ai_tech_radar.sources.arxiv import collect_arxiv
from ai_tech_radar.sources.fixtures import collect_fixtures
from ai_tech_radar.sources.github import collect_github_releases, collect_github_search
from ai_tech_radar.sources.hackernews import collect_hackernews
from ai_tech_radar.sources.huggingface import collect_huggingface_papers
from ai_tech_radar.sources.rss import collect_rss_feeds


def collect_all(config: dict, *, offline: bool, now) -> list[CollectResult]:
    if offline:
        return [collect_fixtures(config, now)]
    results = [collect_rss_feeds(config, now)]
    results.append(collect_huggingface_papers(config, now))
    results.append(collect_arxiv(config, now))
    results.append(collect_github_releases(config, now))
    results.append(collect_github_search(config, now))
    results.append(collect_hackernews(config, now))
    return results
