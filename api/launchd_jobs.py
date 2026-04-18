"""Helpers for surfacing relevant macOS launchd jobs in the WebUI."""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
from pathlib import Path

LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
TRACKED_LABELS = {
    "com.banyar.nexus-webui",
    "com.banyar.nexus-watch",
    "ai.hermes.gateway",
}
TRACKED_HINTS = (
    "nexus",
    "hermes-agent",
    "hermes-webui",
    "nexus-instance",
    "ai.hermes.gateway",
)


def _run(cmd: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)


def _plist_text(data: dict) -> str:
    parts: list[str] = []
    for key in ("Label", "Program", "WorkingDirectory"):
        value = data.get(key)
        if isinstance(value, str):
            parts.append(value)
    for value in data.get("ProgramArguments") or []:
        if isinstance(value, str):
            parts.append(value)
    for value in (data.get("EnvironmentVariables") or {}).values():
        if isinstance(value, str):
            parts.append(value)
    return " ".join(parts).lower()


def _is_relevant_launchd_job(data: dict, plist_path: Path) -> bool:
    label = str(data.get("Label") or "").strip()
    if not label:
        return False
    if label in TRACKED_LABELS:
        return True
    haystack = f"{label} {_plist_text(data)} {plist_path}".lower()
    return any(hint in haystack for hint in TRACKED_HINTS)


def _schedule_display(data: dict) -> str:
    interval = data.get("StartInterval")
    if isinstance(interval, int) and interval > 0:
        if interval % 3600 == 0:
            hours = interval // 3600
            return f"Every {hours}h"
        if interval % 60 == 0:
            minutes = interval // 60
            return f"Every {minutes}m"
        return f"Every {interval}s"

    calendar = data.get("StartCalendarInterval")
    if isinstance(calendar, list) and calendar:
        return "Calendar schedule"
    if isinstance(calendar, dict) and calendar:
        return "Calendar schedule"

    if data.get("RunAtLoad"):
        return "Run at load"
    return "On demand"


def _runtime_info(label: str) -> dict:
    domain = f"gui/{os.getuid()}/{label}"
    result = _run(["launchctl", "print", domain], timeout=15)
    text = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        return {
            "loaded": False,
            "running": False,
            "state": "not loaded",
            "pid": None,
            "last_exit_code": None,
            "text": text.strip(),
        }

    state_match = re.search(r"\bstate = ([^\n]+)", text)
    pid_match = re.search(r"\bpid = (\d+)", text)
    exit_match = re.search(r"\blast exit code = ([^\n]+)", text)
    state = state_match.group(1).strip() if state_match else "loaded"
    return {
        "loaded": True,
        "running": state == "running",
        "state": state,
        "pid": int(pid_match.group(1)) if pid_match else None,
        "last_exit_code": exit_match.group(1).strip() if exit_match else None,
        "text": text.strip(),
    }


def list_launchd_jobs() -> list[dict]:
    if not LAUNCH_AGENTS_DIR.exists():
        return []

    jobs: list[dict] = []
    for plist_path in sorted(LAUNCH_AGENTS_DIR.glob("*.plist")):
        try:
            data = plistlib.loads(plist_path.read_bytes())
        except Exception:
            continue
        if not isinstance(data, dict) or not _is_relevant_launchd_job(data, plist_path):
            continue

        label = str(data.get("Label") or plist_path.stem)
        runtime = _runtime_info(label)
        if runtime["running"]:
            status_class = "active"
            status_label = "running"
        elif runtime["loaded"]:
            status_class = "paused"
            status_label = runtime["state"]
        else:
            status_class = "disabled"
            status_label = "not loaded"

        jobs.append(
            {
                "id": label,
                "label": label,
                "name": str(data.get("Label") or plist_path.stem),
                "plist_path": str(plist_path),
                "schedule_display": _schedule_display(data),
                "run_at_load": bool(data.get("RunAtLoad")),
                "keep_alive": data.get("KeepAlive"),
                "working_directory": data.get("WorkingDirectory"),
                "program": data.get("Program"),
                "program_arguments": data.get("ProgramArguments") or [],
                "stdout_path": data.get("StandardOutPath"),
                "stderr_path": data.get("StandardErrorPath"),
                "status_class": status_class,
                "status_label": status_label,
                "runtime": runtime,
            }
        )

    return sorted(jobs, key=lambda job: job["label"])
