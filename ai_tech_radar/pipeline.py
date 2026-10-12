from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ai_tech_radar.analyze import Analyzer
from ai_tech_radar.config import project_path
from ai_tech_radar.enrich import enrich_items
from ai_tech_radar.filter import prepare_items
from ai_tech_radar.mailer import send_report
from ai_tech_radar.models import ReportEntry, RunStats
from ai_tech_radar.report import email_subject, render_email_html, render_email_text, render_markdown, write_report
from ai_tech_radar.sources import collect_all
from ai_tech_radar.store import Store
from ai_tech_radar.textutil import canonical_url, title_key


@dataclass
class RunResult:
    ok: bool
    markdown_path: Path | None
    html_path: Path | None
    message: str
    stats: RunStats


def run_pipeline(
    config: dict,
    *,
    offline: bool = False,
    send_email: bool = True,
    fresh: bool = False,
    now: datetime | None = None,
) -> RunResult:
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    stats = RunStats()
    data_dir = project_path(config, "data_dir")
    db_name = "offline.sqlite" if offline else "radar.sqlite"
    if fresh and not offline:
        return RunResult(False, None, None, "--fresh is only available with --offline, so live history is left unchanged.", stats)
    db_path = ":memory:" if fresh else data_dir / db_name
    store = Store(db_path)
    try:
        return _run(config, store, stats, clock, offline=offline, send_email=send_email)
    finally:
        store.close()


def _network_ready(host: str) -> bool:
    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


def _wait_for_network(config: dict) -> bool:
    host = str(config.get("email", {}).get("smtp_host") or "smtp.gmail.com")
    timeout = float(config.get("network_wait_seconds", 180))
    deadline = time.monotonic() + timeout
    while True:
        if _network_ready(host):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(10)


def _run(config, store: Store, stats: RunStats, clock: datetime, *, offline: bool, send_email: bool) -> RunResult:
    if not offline and not _wait_for_network(config):
        stats.errors.append("network: the connection was not ready")
        return RunResult(
            False,
            None,
            None,
            "The network was not ready at the scheduled time. No email was sent, and the task will retry.",
            stats,
        )
    collected = collect_all(config, offline=offline, now=clock)
    items = []
    for result in collected:
        stats.per_source[result.source_id] = len(result.items)
        items.extend(result.items)
        if result.error:
            stats.errors.append(f"{result.source_id}: {result.error}")
    stats.fetched = len(items)

    rows = store.conn.execute("SELECT url_key, title_key FROM seen").fetchall()
    seen = {(row[0], row[1]) for row in rows}

    outcome = prepare_items(items, config, now=clock, seen_keys=seen, apply_window=not offline)
    stats.duplicates = outcome.duplicates
    stats.low_value = outcome.low_value
    stats.outside_window = outcome.outside_window
    stats.trimmed = outcome.trimmed

    enrich_errors = enrich_items(outcome.kept, config, offline=offline)
    stats.errors.extend(enrich_errors)

    analyzer = Analyzer(config)
    entries: list[ReportEntry] = []
    decided = []
    report_limit = int(config.get("max_report_items", 8))
    for item in outcome.kept:
        stats.analyzed += 1
        analysis = analyzer.analyze(item, offline=offline)
        stats.analysis_methods.append(analysis.method)
        if report_limit > 0 and len(entries) >= report_limit:
            decided.append((item, "analyzed"))
            continue
        entries.append(ReportEntry(item=item, analysis=analysis))
        decided.append((item, "reported"))
    if analyzer.ollama_error:
        stats.errors.append(f"ollama: {analyzer.ollama_error}")
    stats.reported = len(entries)

    model = config.get("ollama", {}).get("model", "llama3.2")
    markdown = render_markdown(entries, stats, generated_at=clock, offline=offline, model=model)
    email_text = render_email_text(entries, generated_at=clock)
    email_html = render_email_html(entries, generated_at=clock)
    stamp = clock.astimezone(timezone.utc).strftime("%Y-%m-%d")
    if offline:
        stamp = f"{stamp}-offline"
    markdown_path, html_path = write_report(project_path(config, "reports_dir"), stamp, markdown, email_html)

    if stats.fetched == 0 and stats.errors:
        return RunResult(
            False,
            markdown_path,
            html_path,
            f"Report saved to {markdown_path}. The sources could not be reached, so a no-updates email was not sent.",
            stats,
        )

    email_message = "Email was not requested."
    if send_email:
        sent, email_message = send_report(config, email_subject(), email_text, email_html)
        if not sent and config.get("email", {}).get("enabled"):
            return RunResult(
                False,
                markdown_path,
                html_path,
                f"Report saved to {markdown_path}. {email_message} Items were not marked as sent, so the next run can retry delivery.",
                stats,
            )
    elif config.get("email", {}).get("enabled"):
        email_message = "Email is configured and was skipped for this run."

    for item, status in decided:
        if status == "reported" and not any(entry.item.url == item.url for entry in entries):
            status = "analyzed"
        store.mark(canonical_url(item.url), title_key(item.title), item.url, item.title, status)
    mode = "offline" if offline else "live"
    store.record_report(str(markdown_path), len(entries), mode)
    message = f"Report saved to {markdown_path}. {email_message} Items in report: {len(entries)}."
    return RunResult(True, markdown_path, html_path, message, stats)
