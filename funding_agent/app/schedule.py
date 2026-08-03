"""Installs the agent as a local every-morning job.

macOS gets a launchd agent, Linux a systemd user timer; both are user-level
(no sudo) and both catch up after the machine was asleep at the scheduled
time. Anything else falls back to printing a crontab line.
"""

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional

LABEL = "eu.techeu.funding-agent"
PROJECT_DIR = Path(__file__).resolve().parent.parent


def _python() -> str:
    return sys.executable or "python3"


def _parse_time(value: str) -> tuple[int, int]:
    try:
        hour_str, minute_str = value.strip().split(":", 1)
        hour, minute = int(hour_str), int(minute_str)
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid time {value!r}; expected HH:MM (24h), e.g. 08:00") from None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid time {value!r}; expected HH:MM (24h), e.g. 08:00")
    return hour, minute


def _launchd_plist(hour: int, minute: int) -> str:
    log_dir = PROJECT_DIR / "logs"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{_python()}</string>
        <string>-m</string>
        <string>app.cli</string>
        <string>run</string>
    </array>
    <key>WorkingDirectory</key><string>{PROJECT_DIR}</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>{hour}</integer>
        <key>Minute</key><integer>{minute}</integer>
    </dict>
    <key>RunAtLoad</key><false/>
    <key>StandardOutPath</key><string>{log_dir / 'agent.log'}</string>
    <key>StandardErrorPath</key><string>{log_dir / 'agent.err.log'}</string>
</dict>
</plist>
"""


def _systemd_units(hour: int, minute: int) -> tuple[str, str]:
    service = f"""[Unit]
Description=Tech.eu funding agent - daily morning brief

[Service]
Type=oneshot
WorkingDirectory={PROJECT_DIR}
ExecStart={_python()} -m app.cli run
"""
    timer = f"""[Unit]
Description=Run the Tech.eu funding agent every morning

[Timer]
OnCalendar=*-*-* {hour:02d}:{minute:02d}:00
Persistent=true

[Install]
WantedBy=timers.target
"""
    return service, timer


def install(at: str = "08:00") -> str:
    hour, minute = _parse_time(at)
    (PROJECT_DIR / "logs").mkdir(parents=True, exist_ok=True)
    system = platform.system()

    if system == "Darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_launchd_plist(hour, minute), encoding="utf-8")
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True, check=False)
        result = subprocess.run(["launchctl", "load", str(path)], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return f"Wrote {path} but launchctl load failed:\n{result.stderr.strip()}"
        return f"Installed launchd agent at {path}\nRuns every day at {hour:02d}:{minute:02d}. Logs: {PROJECT_DIR / 'logs'}"

    if system == "Linux":
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        service, timer = _systemd_units(hour, minute)
        (unit_dir / f"{LABEL}.service").write_text(service, encoding="utf-8")
        (unit_dir / f"{LABEL}.timer").write_text(timer, encoding="utf-8")
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, check=False)
        result = subprocess.run(
            ["systemctl", "--user", "enable", "--now", f"{LABEL}.timer"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            return (
                f"Wrote units to {unit_dir} but enabling the timer failed:\n{result.stderr.strip()}\n\n"
                f"{_cron_hint(hour, minute)}"
            )
        return (
            f"Installed systemd user timer at {unit_dir}/{LABEL}.timer\n"
            f"Runs every day at {hour:02d}:{minute:02d}.\n"
            "Tip: `loginctl enable-linger $USER` keeps it firing when you're not logged in."
        )

    return _cron_hint(hour, minute)


def _cron_hint(hour: int, minute: int) -> str:
    return (
        "No launchd/systemd on this platform. Add this crontab line "
        "(`crontab -e`) to run it every morning:\n\n"
        f"  {minute} {hour} * * * cd {PROJECT_DIR} && {_python()} -m app.cli run "
        f">> {PROJECT_DIR / 'logs' / 'agent.log'} 2>&1"
    )


def uninstall() -> str:
    system = platform.system()
    if system == "Darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True, check=False)
        if path.exists():
            path.unlink()
            return f"Removed {path}"
        return "Nothing installed."
    if system == "Linux":
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        subprocess.run(["systemctl", "--user", "disable", "--now", f"{LABEL}.timer"], capture_output=True, check=False)
        removed = []
        for name in (f"{LABEL}.timer", f"{LABEL}.service"):
            path = unit_dir / name
            if path.exists():
                path.unlink()
                removed.append(str(path))
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, check=False)
        return "Removed:\n" + "\n".join(removed) if removed else "Nothing installed."
    return "Remove the crontab entry with `crontab -e`."


def status() -> str:
    system = platform.system()
    if system == "Darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        if not path.exists():
            return "Not installed. Run: python -m app.cli schedule install --at 08:00"
        result = subprocess.run(["launchctl", "list", LABEL], capture_output=True, text=True, check=False)
        loaded = "loaded" if result.returncode == 0 else "NOT loaded"
        return f"{path}\nlaunchd: {loaded}"
    if system == "Linux":
        result = subprocess.run(
            ["systemctl", "--user", "list-timers", f"{LABEL}.timer", "--no-pager"],
            capture_output=True, text=True, check=False,
        )
        return result.stdout.strip() or "Not installed. Run: python -m app.cli schedule install --at 08:00"
    return "Scheduling on this platform is via crontab; check with `crontab -l`."
