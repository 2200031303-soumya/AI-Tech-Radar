from __future__ import annotations

import json
from dataclasses import dataclass, field


NOT_STATED = "Not stated in source."


@dataclass
class SourceItem:
    source_id: str
    source_name: str
    title: str
    url: str
    published_at: str | None
    excerpt: str
    authors: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def evidence(self) -> str:
        """Text the summarizer and the grounding check are allowed to use."""
        return "\n".join(
            [
                self.source_name,
                self.title,
                self.url,
                self.published_at or "",
                self.excerpt or "",
                ", ".join(self.authors),
                json.dumps(self.metadata, sort_keys=True, default=str),
            ]
        )


@dataclass
class Analysis:
    relevant: bool
    what_was_introduced: str
    who_introduced_it: str
    what_it_does: str
    why_it_matters: str
    technology: str
    factual_data: str
    use_cases: list[str]
    method: str

    def fields(self) -> dict[str, str]:
        return {
            "What was introduced": self.what_was_introduced,
            "Who introduced it": self.who_introduced_it,
            "What it does": self.what_it_does,
            "Why it matters": self.why_it_matters,
            "Technology / framework / model": self.technology,
            "Factual data": self.factual_data,
        }


@dataclass
class ReportEntry:
    item: SourceItem
    analysis: Analysis


@dataclass
class CollectResult:
    source_id: str
    items: list[SourceItem]
    error: str | None = None


@dataclass
class RunStats:
    per_source: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    fetched: int = 0
    duplicates: int = 0
    low_value: int = 0
    outside_window: int = 0
    trimmed: int = 0
    analyzed: int = 0
    dropped_irrelevant: int = 0
    reported: int = 0
    analysis_methods: list[str] = field(default_factory=list)
