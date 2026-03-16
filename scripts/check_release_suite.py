#!/usr/bin/env python3
"""一键串行执行发布前 smoke。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = [
    "check_frontend_smoke.py",
    "check_admin_flow.py",
    "check_wallet_flow.py",
    "check_post_flow.py",
    "check_series_report_flow.py",
    "check_ops_flow.py",
]


def main():
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5012").rstrip("/")
    py = sys.executable or "python3"
    for script in SCRIPTS:
        path = ROOT / "scripts" / script
        print(f"--- running {script} ---", flush=True)
        result = subprocess.run([py, str(path), base], cwd=str(ROOT))
        if result.returncode != 0:
            print(f"release_suite_failed={script}", file=sys.stderr)
            return result.returncode
    print("release_suite_ok=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
