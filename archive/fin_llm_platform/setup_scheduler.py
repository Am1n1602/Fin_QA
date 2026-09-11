from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path

from ._paths import ORCHESTRATOR_DIR, check_layout

_TASK_NAME = "FinLLM_NIFTY50_Pipeline"
_CRON_TAG = "# fin-llm-platform:nifty50-pipeline -- managed by `finqa-setup`, do not hand-edit"
_STATE_PATH = ORCHESTRATOR_DIR / "schedule_state.json"

# {interval} -> a "minute hour day-of-month month day-of-week" cron
# expression template. Weekly runs Sunday; monthly runs the 1st.
_CRON_SCHEDULE_TEMPLATE = {
    "daily": "{minute} {hour} * * *",
    "weekly": "{minute} {hour} * * 0",
    "monthly": "{minute} {hour} 1 * *",
}
_WINDOWS_SC = {"daily": "DAILY", "weekly": "WEEKLY", "monthly": "MONTHLY"}


def _pipeline_script() -> Path:
    return ORCHESTRATOR_DIR / "run_nifty50_pipeline.py"


def _parse_time(time_str: str) -> tuple[int, int]:
    try:
        hour_s, minute_s = time_str.split(":")
        hour, minute = int(hour_s), int(minute_s)
    except ValueError as exc:
        raise ValueError(f"--time must be HH:MM in 24h format, got {time_str!r}") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"--time must be a valid 24h HH:MM, got {time_str!r}")
    return hour, minute


def _write_state(interval: str, time_str: str) -> None:
    _STATE_PATH.write_text(json.dumps(
        {"interval": interval, "time": time_str, "registered_via": "finqa-setup",
         "os": platform.system()},
        indent=2,
    ) + "\n")


def _register_windows(interval: str, time_str: str) -> None:
    cmd = [
        "schtasks", "/Create", "/F",
        "/SC", _WINDOWS_SC[interval],
        "/TN", _TASK_NAME,
        "/TR", f'"{sys.executable}" "{_pipeline_script()}"',
        "/ST", time_str,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _remove_windows() -> None:
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", _TASK_NAME], check=False, capture_output=True)


def build_cron_line(interval: str, hour: int, minute: int) -> str:
    """Pure, separately testable: the exact crontab line finqa-setup
    would install for a given interval/time (used directly by the unit
    tests -- see test_setup_scheduler.py)."""
    schedule = _CRON_SCHEDULE_TEMPLATE[interval].format(hour=hour, minute=minute)
    log_path = ORCHESTRATOR_DIR / "logs" / "cron.log"
    return f'{schedule} "{sys.executable}" "{_pipeline_script()}" >> "{log_path}" 2>&1 {_CRON_TAG}'


def _register_cron(interval: str, hour: int, minute: int) -> None:
    (ORCHESTRATOR_DIR / "logs").mkdir(parents=True, exist_ok=True)
    new_line = build_cron_line(interval, hour, minute)

    existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    lines = [] if existing.returncode != 0 else existing.stdout.splitlines()
    lines = [ln for ln in lines if _CRON_TAG not in ln]
    lines.append(new_line)

    subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)


def _remove_cron() -> None:
    existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if existing.returncode != 0:
        return  # no crontab at all -- nothing to remove
    lines = [ln for ln in existing.stdout.splitlines() if _CRON_TAG not in ln]
    subprocess.run(["crontab", "-"], input="\n".join(lines) + ("\n" if lines else ""), text=True, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interval", choices=["daily", "weekly", "monthly"], default=None)
    parser.add_argument("--time", default="03:00", help="24h local time, HH:MM (default 03:00)")
    parser.add_argument("--remove", action="store_true", help="Unregister the scheduled job")
    parser.add_argument("--status", action="store_true", help="Show what's currently registered")
    args = parser.parse_args()

    if args.status:
        if _STATE_PATH.exists():
            print(_STATE_PATH.read_text())
        else:
            print("No schedule currently registered by finqa-setup (or its state file is missing).")
        return 0

    if args.remove:
        if platform.system() == "Windows":
            _remove_windows()
        else:
            _remove_cron()
        if _STATE_PATH.exists():
            _STATE_PATH.unlink()
        print("Scheduled NIFTY 50 pipeline job removed.")
        return 0

    if not args.interval:
        parser.error("--interval is required unless --remove or --status is given")

    try:
        hour, minute = _parse_time(args.time)
    except ValueError as exc:
        print(f"finqa-setup: {exc}", file=sys.stderr)
        return 1

    problems = check_layout()
    if problems or not _pipeline_script().exists():
        for p in problems:
            print(f"finqa-setup: {p}", file=sys.stderr)
        print(
            f"finqa-setup: could not find {_pipeline_script()} -- this needs to run from an "
            f"editable install (`pip install -e .` from the project root) with orchestrator/ "
            f"still present alongside fin_llm_platform/ -- see MANUAL.md.",
            file=sys.stderr,
        )
        return 1

    try:
        if platform.system() == "Windows":
            _register_windows(args.interval, args.time)
        else:
            _register_cron(args.interval, hour, minute)
    except FileNotFoundError:
        tool = "schtasks" if platform.system() == "Windows" else "crontab"
        print(
            f"finqa-setup: '{tool}' is not available on this system -- it's normally built into "
            f"the OS, so this usually means something unusual about this environment (e.g. a "
            f"minimal container). Register the scheduled job manually instead: run\n"
            f"    {sys.executable} {_pipeline_script()}\n"
            f"on your own {args.interval} schedule.",
            file=sys.stderr,
        )
        return 1
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        print(
            f"finqa-setup: could not register the scheduled job ({detail}). On Windows this "
            f"sometimes needs an administrator/elevated prompt; on Linux/macOS, make sure your "
            f"user is allowed to use `crontab` (check /etc/cron.allow or /etc/cron.deny).",
            file=sys.stderr,
        )
        return 1

    _write_state(args.interval, args.time)
    print(f"Registered: the NIFTY 50 pipeline will run {args.interval} at {args.time} local time.")
    print(f"Full pipeline command: {sys.executable} {_pipeline_script()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())