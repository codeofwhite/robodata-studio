from __future__ import annotations

import argparse
import json
import os
import signal
import time
from pathlib import Path


def write_ready() -> None:
    raw_path = os.environ.get("ROBOT_DATA_STUDIO_READY_FILE")
    if not raw_path:
        return
    path = Path(raw_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps({"ready": True, "pid": os.getpid()}) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--lifetime", type=float, default=60.0)
    parser.add_argument("--ready-delay", type=float, default=0.0)
    parser.add_argument("--ignore-sigterm", action="store_true")
    args = parser.parse_args()
    stop_requested = False

    def request_stop(_signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(
        signal.SIGTERM,
        signal.SIG_IGN if args.ignore_sigterm else request_stop,
    )
    if args.ready_delay:
        time.sleep(args.ready_delay)
    write_ready()
    started = time.monotonic()
    while not stop_requested and time.monotonic() - started < args.lifetime:
        time.sleep(0.02)
    if args.exit_code is not None:
        return args.exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
