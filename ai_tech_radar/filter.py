from __future__ import annotations

import re
from datetime import datetime

from ai_tech_radar.models import SourceItem
from ai_tech_radar.textutil import canonical_url, contains_term, parse_datetime, title_key, within_hours


class FilterOutcome:
    def __init__(self, kept: list[SourceItem], duplicates: int, low_value: int, outside_window: int, trimmed: int):
        self.kept = kept
        self.duplicates = duplicates
        self.low_value = low_value
        self.outside_window = outside_window
        self.trimmed = trimmed


def _compiled_patterns(config: dict) -> list[re.Pattern]:
    patterns = config.get("filters", {}).get("low_value_patterns", [])
    compiled = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern))
        except re.error:
            continue
    return compiled


_VERB = re.compile(r"(?i)\b(releas\w*|launch\w*|introduc\w*|announc\w*|we present|we propose)\b")
_ARTIFACT = re.compile(
    r"(?i)\b(open[- ]weights?|open[- ]source|benchmark|language model|foundation model|checkpoint|framework|sdk)\b"
)
_VERSION = re.compile(r"(?i)(?:^|[^a-z0-9])v?\d+\.\d+(?:\.\d+)?\b")
_CATEGORIES = ("model", "framework", "tool", "research", "platform")
_TOOL_REPOS = {
    "ollama/ollama",
    "open-webui/open-webui",
    "comfyanonymous/ComfyUI",
    "berriai/litellm",
    "chroma-core/chroma",
    "qdrant/qdrant",
    "sgl-project/sglang",
    "huggingface/text-generation-inference",
}
_MODEL_REPOS = {
    "ggml-org/llama.cpp",
    "unslothai/unsloth",
    "ml-explore/mlx",
    "huggingface/diffusers",
    "NVIDIA/TensorRT-LLM",
}


def _number(item: SourceItem, key: str) -> int:
    value = item.metadata.get(key) or 0
    return int(value) if isinstance(value, (int, float)) else 0


def classify(item: SourceItem) -> str:
    """Place an item in one technology area so the email can cover each area."""
    if item.source_id in {"arxiv", "huggingface-papers"}:
        return "research"
    repo = str(item.metadata.get("repo") or "")
    if repo in _TOOL_REPOS:
        return "tool"
    if repo in _MODEL_REPOS:
        return "model"
    blob = f"{item.title} {item.excerpt}".lower()
    if any(word in blob for word in ("open-weight", "open weight", "language model", "foundation model", "checkpoint")):
        return "model"
    if item.source_id == "github-releases" or any(word in blob for word in ("framework", "library", "sdk", "pytorch")):
        return "framework"
    if any(word in blob for word in ("cli", "playground", "developer tool", "ide ")):
        return "tool"
    if item.source_id in {"hackernews", "github-search"}:
        return "tool"
    return "platform"


def is_concrete_update(item: SourceItem) -> bool:
    """Keep a release, model, framework, tool, or research result. Drop essays and tips."""
    title = item.title or ""
    text = f"{title}\n{item.excerpt or ''}"
    if item.source_id == "arxiv":
        return bool(_VERB.search(title) or _ARTIFACT.search(title) or re.search(r"(?i)\b(model|agent|dataset)\b", title))
    if item.source_id == "huggingface-papers" and _number(item, "upvotes") >= 10:
        return True
    if item.metadata.get("release") or _VERSION.search(text) or _VERB.search(text) or _ARTIFACT.search(text):
        return True
    if _number(item, "stars") >= 200:
        return True
    if _number(item, "points") >= 150 and (_VERB.search(title) or _ARTIFACT.search(title)):
        return True
    return False


def is_low_value(item: SourceItem, config: dict, patterns: list[re.Pattern] | None = None) -> bool:
    text = f"{item.title}\n{item.excerpt}"
    compiled = patterns if patterns is not None else _compiled_patterns(config)
    if any(pattern.search(text) for pattern in compiled):
        return True
    filters = config.get("filters", {})
    terms = filters.get("ai_terms", [])
    broad = set(filters.get("broad_source_ids", ["hackernews", "microsoft-research", "aws-ml", "nvidia", "google-research"]))
    require = bool(item.metadata.get("require_ai_terms")) or item.source_id in broad
    if require and terms and not any(contains_term(text, term) for term in terms):
        return True
    if not is_concrete_update(item):
        return True
    return False


def select_balanced(items: list[SourceItem], limit: int) -> list[SourceItem]:
    """Take the strongest item from each technology area before filling the rest."""
    buckets: dict[str, list[SourceItem]] = {category: [] for category in _CATEGORIES}
    for item in items:
        category = classify(item)
        item.metadata["category"] = category
        buckets.setdefault(category, []).append(item)
    selected: list[SourceItem] = []
    while len(selected) < limit:
        added = False
        for category in _CATEGORIES:
            bucket = buckets.get(category) or []
            if bucket and len(selected) < limit:
                selected.append(bucket.pop(0))
                added = True
        if not added:
            break
    return selected


def prepare_items(
    items: list[SourceItem],
    config: dict,
    *,
    now: datetime,
    seen_keys: set[tuple[str, str]] | None = None,
    apply_window: bool = True,
) -> FilterOutcome:
    patterns = _compiled_patterns(config)
    hours = int(config.get("lookback_hours", 36))
    already = seen_keys or set()
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    duplicates = 0
    low_value = 0
    outside = 0
    trimmed = 0
    ranked = sorted(items, key=lambda item: int(item.metadata.get("priority", 50)), reverse=True)
    per_source_cap = config.get("max_per_source", {})
    per_source_count: dict[str, int] = {}
    kept: list[SourceItem] = []
    seen_url_keys = {url for url, _title in already}
    seen_title_keys = {title for _url, title in already if title}

    for item in ranked:
        url_key = canonical_url(item.url)
        item_title = title_key(item.title)
        published = parse_datetime(item.published_at)
        if apply_window and published is not None and not within_hours(published, now, hours):
            outside += 1
            continue
        if apply_window and published is None and item.source_id not in {"huggingface-papers"}:
            outside += 1
            continue
        if not url_key or not item_title:
            low_value += 1
            continue
        if url_key in seen_urls or url_key in seen_url_keys or item_title in seen_titles or item_title in seen_title_keys:
            duplicates += 1
            continue
        if is_low_value(item, config, patterns):
            low_value += 1
            continue
        cap = int(per_source_cap.get(item.source_id, per_source_cap.get("default", 6)))
        count = per_source_count.get(item.source_id, 0)
        if count >= cap:
            trimmed += 1
            continue
        seen_urls.add(url_key)
        seen_titles.add(item_title)
        per_source_count[item.source_id] = count + 1
        kept.append(item)

    def engagement(item: SourceItem) -> int:
        total = 0
        for key in ("stars", "points", "upvotes"):
            value = item.metadata.get(key)
            if isinstance(value, (int, float)):
                total = max(total, int(value))
        return total

    kept.sort(key=lambda item: (int(item.metadata.get("priority", 50)), engagement(item)), reverse=True)
    limit = int(config.get("max_items_to_analyze", 12))
    balanced = select_balanced(kept, limit)
    trimmed += max(len(kept) - len(balanced), 0)
    return FilterOutcome(balanced, duplicates, low_value, outside, trimmed)
