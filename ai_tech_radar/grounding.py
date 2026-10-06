from __future__ import annotations

import re

from ai_tech_radar.models import NOT_STATED, Analysis, SourceItem
from ai_tech_radar.textutil import split_sentences


_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def number_tokens(text: str) -> set[str]:
    cleaned = (text or "").replace(",", "")
    return {match.group(0) for match in _NUMBER.finditer(cleaned)}


def _supported(sentence: str, allowed: set[str]) -> bool:
    return number_tokens(sentence).issubset(allowed)


def ground_text(text: str, evidence: str) -> str:
    raw = (text or "").strip()
    if not raw or raw == NOT_STATED:
        return NOT_STATED
    allowed = number_tokens(evidence)
    sentences = split_sentences(raw)
    if not sentences:
        sentences = [raw]
    kept = [sentence for sentence in sentences if _supported(sentence, allowed)]
    if not kept:
        return NOT_STATED
    return " ".join(kept)


def ground_analysis(analysis: Analysis, item: SourceItem) -> Analysis:
    evidence = item.evidence()
    use_cases = []
    for case in analysis.use_cases:
        grounded = ground_text(case, evidence)
        if grounded != NOT_STATED:
            use_cases.append(grounded)
    return Analysis(
        relevant=analysis.relevant,
        what_was_introduced=ground_text(analysis.what_was_introduced, evidence),
        who_introduced_it=ground_text(analysis.who_introduced_it, evidence),
        what_it_does=ground_text(analysis.what_it_does, evidence),
        why_it_matters=ground_text(analysis.why_it_matters, evidence),
        technology=ground_text(analysis.technology, evidence),
        factual_data=ground_text(analysis.factual_data, evidence),
        use_cases=use_cases,
        method=analysis.method,
    )
