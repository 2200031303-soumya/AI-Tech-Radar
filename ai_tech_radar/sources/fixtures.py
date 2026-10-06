from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ai_tech_radar.config import PROJECT_ROOT
from ai_tech_radar.models import CollectResult, SourceItem


def fixture_path() -> Path:
    return PROJECT_ROOT / "fixtures" / "sample_items.json"


def load_fixture_items(now: datetime | None = None, path: Path | None = None) -> list[SourceItem]:
    clock = now or datetime.now(timezone.utc)
    payload = json.loads((path or fixture_path()).read_text(encoding="utf-8"))
    items: list[SourceItem] = []
    for row in payload:
        published = row.get("published_at")
        if published in {None, "", "now"}:
            published = clock.astimezone(timezone.utc).isoformat()
        items.append(
            SourceItem(
                source_id=row["source_id"],
                source_name=row["source_name"],
                title=row["title"],
                url=row["url"],
                published_at=published,
                excerpt=row.get("excerpt") or "",
                authors=list(row.get("authors") or []),
                metadata=dict(row.get("metadata") or {}),
            )
        )
    return items


def collect_fixtures(config: dict, now: datetime) -> CollectResult:
    del config
    return CollectResult("fixtures", load_fixture_items(now))
