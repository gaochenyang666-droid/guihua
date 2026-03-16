#!/usr/bin/env python3
"""手动执行一轮待发布补偿，可用于 cron / Render 定时任务。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app import app, PendingPublication, _resume_pending_publication_row  # noqa: E402
from services.publish_compensation import run_compensation_batch  # noqa: E402


def main():
    limit = 10
    if len(sys.argv) > 1:
        try:
            limit = max(1, int(sys.argv[1]))
        except Exception:
            limit = 10
    result = run_compensation_batch(
        app,
        PendingPublication,
        _resume_pending_publication_row,
        app.logger,
        limit=limit,
        min_age_seconds=0,
    )
    print(
        "publish_compensation_ok=1 "
        f"processed={result.get('processed', 0)} "
        f"recovered={result.get('recovered', 0)} "
        f"skipped={result.get('skipped', 0)} "
        f"errors={result.get('errors', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
