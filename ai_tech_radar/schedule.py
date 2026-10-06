from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape


# India Standard Time does not observe daylight saving.
IST = timezone(timedelta(hours=5, minutes=30), name="IST")
TASK_NAME = "AI Tech Radar"


def parse_hhmm(value: str) -> tuple[int, int]:
    hour, minute = (int(part) for part in value.split(":", 1))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid schedule time: {value}")
    return hour, minute


def schedule_zone(config: dict) -> timezone:
    name = str(config.get("schedule_timezone") or "Asia/Kolkata")
    if name in {"Asia/Kolkata", "Asia/Calcutta", "IST", "India Standard Time"}:
        return IST
    return IST


def next_run(now: datetime, when: str = "08:00", zone: timezone = IST) -> datetime:
    """Return the next 8:00am-style instant in the schedule timezone."""
    current = now if now.tzinfo is not None else now.replace(tzinfo=zone)
    local_now = current.astimezone(zone)
    hour, minute = parse_hhmm(when)
    target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= local_now:
        target += timedelta(days=1)
    return target


def install_daily_task(config: dict, now: datetime | None = None) -> str:
    """Register a Windows task that runs the radar every day at 8:00am IST."""
    if sys.platform != "win32":
        return "The daily task can be registered on Windows Task Scheduler."
    import subprocess

    clock = now or datetime.now(IST)
    when = str(config.get("schedule_time") or "08:00")
    upcoming = next_run(clock, when, schedule_zone(config))
    local_start = upcoming.astimezone().replace(microsecond=0)
    root = Path(config.get("_root") or ".").resolve()
    python = Path(sys.executable).resolve()
    recipient = config.get("email", {}).get("to") or "saisoumya.dolly@gmail.com"
    description = (
        f"Send the AI Tech Radar report to {recipient} every day at {when} India Standard Time."
    )
    xml = _task_xml(
        python=str(python),
        working_directory=str(root),
        start_local=local_start.strftime("%Y-%m-%dT%H:%M:%S"),
        description=description,
    )
    xml_path = root / "data" / "ai-tech-radar-task.xml"
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.write_text(xml, encoding="utf-16")
    completed = subprocess.run(
        ["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/XML", str(xml_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    detail = (completed.stdout or completed.stderr or "").strip()
    if completed.returncode != 0:
        return f"Could not register the daily task. {detail}"
    local_clock = local_start.strftime("%H:%M")
    return (
        f"Scheduled task '{TASK_NAME}' is registered. "
        f"It runs every day at {when} IST ({local_clock} on this computer) and emails {recipient}. {detail}"
    )


def _task_xml(*, python: str, working_directory: str, start_local: str, description: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{escape(description)}</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start_local}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(python)}</Command>
      <Arguments>-m ai_tech_radar run</Arguments>
      <WorkingDirectory>{escape(working_directory)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""
