from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

from ai_tech_radar import __version__
from ai_tech_radar.config import load_config, project_path
from ai_tech_radar.http_client import HttpError, get_json
from ai_tech_radar.mailer import can_send, send_report
from ai_tech_radar.pipeline import run_pipeline
from ai_tech_radar.schedule import IST, install_daily_task, next_run, schedule_zone


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai_tech_radar",
        description="Collect daily AI releases from configured sources, summarize them with local Ollama, and save or email a tech radar.",
    )
    parser.add_argument("--config", help="Path to config.json")
    parser.add_argument("--version", action="version", version=f"AI Tech Radar {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Collect sources, summarize, and write today's report")
    run.add_argument("--offline", action="store_true", help="Use local sample sources and skip every external request")
    run.add_argument("--no-email", action="store_true", help="Write the report and do not send email")
    run.add_argument("--fresh", action="store_true", help="With --offline, ignore previously seen sample items")
    run.add_argument("--lookback-hours", type=int, help="Override the collection window")

    sub.add_parser("test-ollama", help="Check that the local Ollama server answers")
    sub.add_parser("test-email", help="Send a short test message with the configured SMTP settings")

    schedule = sub.add_parser("schedule", help="Show or install the daily 8:00am IST task")
    schedule.add_argument("--install", action="store_true", help="Register the Windows task that emails the report every day at 8:00am IST")
    schedule.add_argument("--serve", action="store_true", help="Stay running and execute the radar every day at 8:00am IST")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except (OSError, ValueError) as exc:
        print(f"Could not load config: {exc}", file=sys.stderr)
        return 1
    if args.command == "run":
        if args.lookback_hours:
            config["lookback_hours"] = args.lookback_hours
        result = run_pipeline(
            config,
            offline=args.offline,
            send_email=not args.no_email,
            fresh=args.fresh,
        )
        print(result.message)
        _print_stats(result.stats)
        code = 0 if result.ok else 1
        _append_log(config, f"exit={code} {result.message}")
        return code
    if args.command == "test-ollama":
        return _test_ollama(config)
    if args.command == "test-email":
        return _test_email(config)
    if args.command == "schedule":
        return _schedule(config, serve=args.serve, install=args.install)
    parser.print_help()
    return 1


def _print_stats(stats) -> None:
    print(
        "Fetched {fetched}. Duplicates {duplicates}. Low-value {low_value}. "
        "Analyzed {analyzed}. Reported {reported}.".format(
            fetched=stats.fetched,
            duplicates=stats.duplicates,
            low_value=stats.low_value,
            analyzed=stats.analyzed,
            reported=stats.reported,
        )
    )
    for error in stats.errors:
        print(f"Note: {error}")


def _test_ollama(config: dict) -> int:
    ollama = config.get("ollama", {})
    host = str(ollama.get("host") or "http://127.0.0.1:11434").rstrip("/")
    timeout = min(float(ollama.get("timeout_seconds", 90)), 5)
    try:
        payload = get_json(host + "/api/tags", timeout, config.get("user_agent", "AI-Tech-Radar/0.1"))
    except (HttpError, OSError, ValueError, TimeoutError) as exc:
        print(f"Ollama is not reachable at {host}: {exc}")
        print("Start Ollama and pull the configured model, then run this command again.")
        return 1
    models = [row.get("name") for row in payload.get("models", []) if isinstance(row, dict)]
    print(f"Ollama is reachable at {host}.")
    if models:
        print("Models: " + ", ".join(str(model) for model in models))
    else:
        print("No models are installed yet. Pull the model named in config.json.")
    return 0


def _test_email(config: dict) -> int:
    ready, reason = can_send(config)
    if not ready:
        print(reason)
        return 1
    sent, message = send_report(
        config,
        "AI Tech Radar test",
        "This is a test message from AI Tech Radar.",
        "<p>This is a test message from AI Tech Radar.</p>",
    )
    print(message)
    return 0 if sent else 1


def _schedule(config: dict, *, serve: bool, install: bool) -> int:
    when = str(config.get("schedule_time") or "08:00")
    zone = schedule_zone(config)
    upcoming = next_run(datetime.now(zone), when, zone)
    recipient = config.get("email", {}).get("to") or "saisoumya.dolly@gmail.com"
    print(f"Recipient: {recipient}")
    print(f"Daily run: {when} India Standard Time.")
    print(f"Next run: {upcoming.strftime('%Y-%m-%d %H:%M IST')}.")
    if install:
        message = install_daily_task(config)
        print(message)
        return 0 if message.startswith("Scheduled task") else 1
    if not serve:
        print("Run 'python -m ai_tech_radar schedule --install' to register the Windows task.")
        return 0
    print("Scheduler is running. The radar waits until 8:00am IST.")
    while True:
        _sleep_until(config)
        result = run_pipeline(config, offline=False, send_email=True, fresh=False)
        print(result.message)
        _append_log(config, result.message)


def _sleep_until(config: dict) -> None:
    when = str(config.get("schedule_time") or "08:00")
    zone = schedule_zone(config)
    target = next_run(datetime.now(zone), when, zone)
    delay = (target - datetime.now(zone)).total_seconds()
    time.sleep(max(delay, 1))


def _append_log(config: dict, line: str) -> None:
    path = project_path(config, "data_dir") / "scheduler.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {line}\n")
