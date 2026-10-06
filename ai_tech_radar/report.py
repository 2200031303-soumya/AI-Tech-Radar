from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from ai_tech_radar.models import NOT_STATED, ReportEntry, RunStats
from ai_tech_radar.schedule import IST
from ai_tech_radar.textutil import parse_datetime

_AREA_LABELS = {
    "model": "Model",
    "framework": "Framework",
    "tool": "Developer tool",
    "research": "Research",
    "platform": "Product update",
}


def email_subject() -> str:
    return "What's new today"


def _area_label(entry: ReportEntry) -> str:
    category = str(entry.item.metadata.get("category") or "")
    return _AREA_LABELS.get(category, "Technology update")


def _useful_lines(entry: ReportEntry) -> list[tuple[str, str]]:
    analysis = entry.analysis
    lines = [(label, value) for label, value in analysis.fields().items() if value and value != NOT_STATED]
    if analysis.use_cases:
        lines.append(("Potential real-world use cases", " ".join(analysis.use_cases)))
    lines.append(("Original source", f"{entry.item.source_name} - {entry.item.url}"))
    return lines


def format_published(value: str | None) -> str:
    parsed = parse_datetime(value)
    if parsed is None:
        return value or NOT_STATED
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def _mode_note(stats: RunStats, *, offline: bool, model: str) -> str:
    methods = set(stats.analysis_methods)
    if offline:
        return (
            "Offline sample run. Live feeds were not contacted. "
            "Each summary is copied from the fixture source text, and every numeric claim is limited to numbers present in that source."
        )
    if methods and all(method.startswith("ollama:") for method in methods):
        return (
            f"Summaries were drafted by the local Ollama model ({model}) and checked so numeric claims stay inside the retrieved source text. "
            "Fields without support in the source say \"Not stated in source.\""
        )
    if any(method.startswith("ollama:") for method in methods):
        return (
            f"Some summaries were drafted by the local Ollama model ({model}). "
            "Items that the model could not reach use an extractive copy of the source. "
            "Numeric claims that were not in the source were removed."
        )
    if "extractive-fallback" in methods:
        return (
            "Ollama was not reachable. Summaries are extractive copies of the retrieved source text, "
            "so the report does not add facts beyond those sources."
        )
    return (
        "Summaries are extractive copies of the retrieved source text. "
        "Fields without support in the source say \"Not stated in source.\""
    )


def render_markdown(
    entries: list[ReportEntry],
    stats: RunStats,
    *,
    generated_at: datetime,
    offline: bool,
    model: str,
) -> str:
    stamp = generated_at.strftime("%Y-%m-%d")
    lines = [
        f"# AI Tech Radar - {stamp}",
        "",
        _mode_note(stats, offline=offline, model=model),
        "",
    ]
    if not entries:
        lines.append("No new relevant developments were found in this collection window.")
        lines.append("")
    for index, entry in enumerate(entries, start=1):
        item = entry.item
        analysis = entry.analysis
        lines.append(f"## {index}. {item.title}")
        lines.append("")
        for label, value in analysis.fields().items():
            lines.append(f"- **{label}:** {value}")
        if analysis.use_cases:
            lines.append("- **Potential real-world use cases:**")
            for case in analysis.use_cases:
                lines.append(f"  - {case}")
        else:
            lines.append(f"- **Potential real-world use cases:** {NOT_STATED}")
        lines.append(f"- **Original source:** {item.source_name} - {item.url}")
        lines.append(f"- **Published:** {format_published(item.published_at)}")
        lines.append(f"- **Summary method:** {analysis.method}")
        lines.append("")
    lines.extend(_footer(stats))
    return "\n".join(lines).rstrip() + "\n"


def render_email_text(entries: list[ReportEntry], *, generated_at: datetime) -> str:
    """Plain-text body for the daily email. Empty fields and run logs stay out."""
    day = generated_at.astimezone(IST).strftime("%d %B %Y")
    lines = ["What's new today", day, ""]
    if not entries:
        lines.append("No strong technology updates today.")
        lines.append("")
        return "\n".join(lines)
    for index, entry in enumerate(entries, start=1):
        lines.append(f"{index}. {_area_label(entry)}: {entry.item.title}")
        for label, value in _useful_lines(entry):
            lines.append(f"- {label}: {value}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_email_html(entries: list[ReportEntry], *, generated_at: datetime) -> str:
    """HTML body for the daily email. Empty fields and run logs stay out."""
    day = generated_at.astimezone(IST).strftime("%d %B %Y")
    blocks = [
        "<!DOCTYPE html>",
        "<html><head><meta charset=\"utf-8\"></head>",
        "<body style=\"margin:0;padding:24px;background:#f6f7f9;color:#1c1c1c;font-family:Georgia,serif;\">",
        "<div style=\"max-width:720px;margin:0 auto;background:#ffffff;padding:28px 32px;border:1px solid #e4e4e4;\">",
        "<h1 style=\"font-size:24px;margin:0 0 4px;\">What's new today</h1>",
        f"<p style=\"margin:0 0 20px;color:#555;\">{html.escape(day)}</p>",
    ]
    if not entries:
        blocks.append("<p>No strong technology updates today.</p>")
    for index, entry in enumerate(entries, start=1):
        title = f"{index}. {_area_label(entry)}: {entry.item.title}"
        blocks.append(f"<h2 style=\"font-size:18px;margin:28px 0 8px;\">{html.escape(title)}</h2>")
        blocks.append("<ul style=\"padding-left:18px;line-height:1.5;\">")
        for label, value in _useful_lines(entry):
            if label == "Original source":
                blocks.append(
                    "<li><strong>Original source:</strong> "
                    f"<a href=\"{html.escape(entry.item.url, quote=True)}\">{html.escape(value)}</a></li>"
                )
            else:
                blocks.append(f"<li><strong>{html.escape(label)}:</strong> {html.escape(value)}</li>")
        blocks.append("</ul>")
    blocks.append("</div></body></html>")
    return "\n".join(blocks)


def render_html(
    entries: list[ReportEntry],
    stats: RunStats,
    *,
    generated_at: datetime,
    offline: bool,
    model: str,
) -> str:
    stamp = generated_at.strftime("%Y-%m-%d")
    blocks = [
        "<!DOCTYPE html>",
        "<html><head><meta charset=\"utf-8\"></head>",
        "<body style=\"margin:0;padding:24px;background:#f6f7f9;color:#1c1c1c;font-family:Georgia,serif;\">",
        "<div style=\"max-width:720px;margin:0 auto;background:#ffffff;padding:28px 32px;border:1px solid #e4e4e4;\">",
        f"<h1 style=\"font-size:24px;margin:0 0 8px;\">AI Tech Radar - {html.escape(stamp)}</h1>",
        f"<p style=\"line-height:1.5;\">{html.escape(_mode_note(stats, offline=offline, model=model))}</p>",
    ]
    if not entries:
        blocks.append("<p>No new relevant developments were found in this collection window.</p>")
    for index, entry in enumerate(entries, start=1):
        item = entry.item
        analysis = entry.analysis
        blocks.append(f"<h2 style=\"font-size:18px;margin:28px 0 8px;\">{index}. {html.escape(item.title)}</h2>")
        blocks.append("<ul style=\"padding-left:18px;line-height:1.5;\">")
        for label, value in analysis.fields().items():
            blocks.append(f"<li><strong>{html.escape(label)}:</strong> {html.escape(value)}</li>")
        blocks.append("<li><strong>Potential real-world use cases:</strong>")
        if analysis.use_cases:
            blocks.append("<ul>")
            for case in analysis.use_cases:
                blocks.append(f"<li>{html.escape(case)}</li>")
            blocks.append("</ul>")
        else:
            blocks.append(f" {html.escape(NOT_STATED)}")
        blocks.append("</li>")
        source = f"{item.source_name} - {item.url}"
        blocks.append(
            f"<li><strong>Original source:</strong> <a href=\"{html.escape(item.url, quote=True)}\">{html.escape(source)}</a></li>"
        )
        blocks.append(f"<li><strong>Published:</strong> {html.escape(format_published(item.published_at))}</li>")
        blocks.append(f"<li><strong>Summary method:</strong> {html.escape(analysis.method)}</li>")
        blocks.append("</ul>")
    blocks.append("<hr style=\"border:none;border-top:1px solid #e4e4e4;margin:28px 0;\">")
    blocks.append("<ul style=\"padding-left:18px;line-height:1.5;color:#444;\">")
    for line in _footer(stats):
        if line.startswith("- "):
            blocks.append(f"<li>{html.escape(line[2:])}</li>")
    blocks.append("</ul></div></body></html>")
    return "\n".join(blocks)


def _footer(stats: RunStats) -> list[str]:
    source_bits = ", ".join(f"{name} {count}" for name, count in sorted(stats.per_source.items())) or "none"
    lines = [
        "## Run notes",
        "",
        f"- Items fetched: {stats.fetched}",
        f"- Duplicates removed: {stats.duplicates}",
        f"- Low-value items removed: {stats.low_value}",
        f"- Outside the collection window: {stats.outside_window}",
        f"- Trimmed after the per-source cap: {stats.trimmed}",
        f"- Items analyzed: {stats.analyzed}",
        f"- Dropped as not relevant: {stats.dropped_irrelevant}",
        f"- Items in this report: {stats.reported}",
        f"- Items by source: {source_bits}",
    ]
    if stats.errors:
        lines.append("- Source notes: " + " | ".join(stats.errors))
    return lines


def write_report(directory: Path, stamp: str, markdown: str, html_body: str) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    markdown_path = directory / f"{stamp}.md"
    html_path = directory / f"{stamp}.html"
    markdown_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(html_body, encoding="utf-8")
    return markdown_path, html_path
