from __future__ import annotations

import json
import re

from ai_tech_radar.grounding import ground_analysis
from ai_tech_radar.http_client import HttpError, post_json
from ai_tech_radar.models import NOT_STATED, Analysis, SourceItem
from ai_tech_radar.textutil import split_sentences


_TECHNOLOGIES = [
    "PyTorch",
    "TensorFlow",
    "JAX",
    "CUDA",
    "Hugging Face",
    "Transformers",
    "vLLM",
    "Ollama",
    "LangChain",
    "LlamaIndex",
    "llama.cpp",
    "Diffusers",
    "LoRA",
    "QLoRA",
    "ONNX",
    "TensorRT",
    "Triton",
    "ComfyUI",
    "Stable Diffusion",
    "mixture-of-experts",
    "MoE",
    "RAG",
    "Transformer",
]


_SYSTEM = """You are a precise analyst for a daily AI tech radar.
Use only the SOURCE packet in the user message. Do not add facts from prior knowledge.
Return one JSON object with these keys:
- relevant: boolean. Use true only for a new or updated model, framework, developer tool, research method, or major product capability. Use false for hiring posts, tutorials, weekly digests, opinion pieces, policy notes, events, and marketing with no specific technology.
- what_was_introduced: one sentence naming the release
- who_introduced_it: people or organizations named in the source, otherwise exactly "Not stated in source."
- what_it_does: one or two sentences
- why_it_matters: one sentence supported by the source, otherwise exactly "Not stated in source."
- technology: frameworks, models, or libraries named in the source, otherwise exactly "Not stated in source."
- factual_data: only numbers, versions, star counts, benchmarks, and dates that appear in the source packet. If none, exactly "Not stated in source."
- use_cases: array of short strings describing uses that the source states. If none, an empty array.
Never invent metrics, parameter counts, benchmarks, star counts, or release names.
Do not include a number that is absent from the source packet."""


def extractive_analysis(item: SourceItem) -> Analysis:
    sentences = split_sentences(item.excerpt)
    who = ", ".join(author for author in item.authors if author) or item.source_name
    what_it_does = " ".join(sentences[:2]) if sentences else NOT_STATED
    why = _why_it_matters(sentences)
    blob = f"{item.title}\n{item.excerpt}"
    found = [name for name in _TECHNOLOGIES if name.lower() in blob.lower()]
    technology = ", ".join(found) if found else NOT_STATED
    facts = _facts_from_item(item, sentences)
    use_cases = []
    for sentence in sentences:
        lowered = sentence.lower()
        if "can use" in lowered or "use it" in lowered or "used for" in lowered or "use cases" in lowered:
            use_cases.append(sentence)
    return ground_analysis(
        Analysis(
            relevant=True,
            what_was_introduced=item.title,
            who_introduced_it=who,
            what_it_does=what_it_does,
            why_it_matters=why,
            technology=technology,
            factual_data=facts,
            use_cases=use_cases,
            method="extractive",
        ),
        item,
    )


def _why_it_matters(sentences: list[str]) -> str:
    """Prefer a result stated in the source over the sentence that only names the release."""
    strong = ("benchmark", "throughput", "outperform", "faster", "cuts", "reduces", "improves", "gain")
    weak = ("open-weight", "open source", "open-source", "enables")
    opening = set(sentences[:2])

    def pick(cues: tuple[str, ...], skip: set[str]) -> str | None:
        for sentence in sentences:
            if sentence in skip:
                continue
            lowered = sentence.lower()
            if any(cue in lowered for cue in cues):
                return sentence
        return None

    return pick(strong, opening) or pick(strong, set()) or pick(weak, opening) or NOT_STATED


def _facts_from_item(item: SourceItem, sentences: list[str]) -> str:
    parts: list[str] = []
    stars = item.metadata.get("stars")
    if isinstance(stars, int):
        parts.append(f"GitHub stars: {stars} (from GitHub).")
    upvotes = item.metadata.get("upvotes")
    if isinstance(upvotes, int):
        parts.append(f"Hugging Face upvotes: {upvotes} (from Hugging Face).")
    points = item.metadata.get("points")
    if isinstance(points, int):
        parts.append(f"Hacker News points: {points} (from Hacker News).")
    release = item.metadata.get("release")
    if release:
        parts.append(f"Release: {release} (from the source).")
    license_name = item.metadata.get("license")
    if license_name and license_name != "NOASSERTION":
        parts.append(f"License: {license_name} (from GitHub).")
    for sentence in sentences:
        if re.search(r"\d", sentence):
            parts.append(sentence)
    if not parts:
        return NOT_STATED
    unique: list[str] = []
    for part in parts:
        if part not in unique:
            unique.append(part)
    return " ".join(unique)


def parse_model_json(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"```$", "", raw).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("model output is not a JSON object")
    return data


def analysis_from_payload(payload: dict, method: str) -> Analysis:
    use_cases = payload.get("use_cases") or []
    if isinstance(use_cases, str):
        use_cases = [use_cases]
    if not isinstance(use_cases, list):
        use_cases = []
    cleaned_cases = [str(case).strip() for case in use_cases if str(case).strip()]
    relevant = payload.get("relevant", True)
    if isinstance(relevant, str):
        relevant = relevant.strip().lower() in {"true", "yes", "1"}
    return Analysis(
        relevant=bool(relevant),
        what_was_introduced=str(payload.get("what_was_introduced") or NOT_STATED).strip() or NOT_STATED,
        who_introduced_it=str(payload.get("who_introduced_it") or NOT_STATED).strip() or NOT_STATED,
        what_it_does=str(payload.get("what_it_does") or NOT_STATED).strip() or NOT_STATED,
        why_it_matters=str(payload.get("why_it_matters") or NOT_STATED).strip() or NOT_STATED,
        technology=str(payload.get("technology") or NOT_STATED).strip() or NOT_STATED,
        factual_data=str(payload.get("factual_data") or NOT_STATED).strip() or NOT_STATED,
        use_cases=cleaned_cases,
        method=method,
    )


def _source_packet(item: SourceItem) -> str:
    authors = ", ".join(item.authors) if item.authors else NOT_STATED
    return (
        f"Source name: {item.source_name}\n"
        f"Title: {item.title}\n"
        f"URL: {item.url}\n"
        f"Published: {item.published_at or NOT_STATED}\n"
        f"Authors: {authors}\n"
        f"Metadata JSON: {json.dumps(item.metadata, sort_keys=True, default=str)}\n"
        f"Source text:\n{item.excerpt or NOT_STATED}\n"
    )


class Analyzer:
    def __init__(self, config: dict):
        self.config = config
        self.ollama_error: str | None = None

    def analyze(self, item: SourceItem, *, offline: bool) -> Analysis:
        ollama = self.config.get("ollama", {})
        if offline or not ollama.get("enabled", True):
            return extractive_analysis(item)
        try:
            drafted = self._ollama(item)
        except (HttpError, OSError, ValueError, TimeoutError, json.JSONDecodeError) as exc:
            self.ollama_error = str(exc)
            if ollama.get("fallback_extractive", True):
                analysis = extractive_analysis(item)
                analysis.method = "extractive-fallback"
                return analysis
            raise
        grounded = ground_analysis(drafted, item)
        if not grounded.relevant:
            return grounded
        if grounded.what_was_introduced == NOT_STATED:
            grounded.what_was_introduced = item.title
        return grounded

    def _ollama(self, item: SourceItem) -> Analysis:
        ollama = self.config.get("ollama", {})
        host = str(ollama.get("host") or "http://127.0.0.1:11434").rstrip("/")
        model = ollama.get("model") or "llama3.2"
        timeout = float(ollama.get("timeout_seconds", 90))
        body = {
            "model": model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": _source_packet(item)},
            ],
            "options": {"temperature": 0},
        }
        payload = post_json(
            host + "/api/chat",
            body,
            timeout,
            self.config.get("user_agent", "AI-Tech-Radar/0.1"),
        )
        message = payload.get("message") or {}
        content = message.get("content") or payload.get("response") or ""
        parsed = parse_model_json(content)
        return analysis_from_payload(parsed, method=f"ollama:{model}")
