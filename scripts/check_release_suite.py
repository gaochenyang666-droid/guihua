#!/usr/bin/env python3
"""一键串行执行发布前 smoke。"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = [
    "check_frontend_smoke.py",
    "check_browser_auth_flow.py",
    "check_admin_flow.py",
    "check_wallet_flow.py",
    "check_post_flow.py",
    "check_series_report_flow.py",
    "check_ops_flow.py",
]

_SKIP_RE = re.compile(r"\b([a-zA-Z0-9_]+_skipped)=1\b")


def _extract_skipped_keys(stdout: str, stderr: str) -> list[str]:
    keys = set()
    for m in _SKIP_RE.finditer(stdout or ""):
        keys.add(m.group(1))
    for m in _SKIP_RE.finditer(stderr or ""):
        keys.add(m.group(1))
    return sorted(keys)


def _is_script_level_skipped(skipped_keys: list[str]) -> bool:
    # 约定：*_flow_skipped=1 代表该脚本整体在远程模式安全跳过
    return any(k.endswith("_flow_skipped") for k in skipped_keys)


def main():
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5012").rstrip("/")
    py = sys.executable or "python3"
    passed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    for script in SCRIPTS:
        path = ROOT / "scripts" / script
        print(f"--- running {script} ---", flush=True)
        result = subprocess.run(
            [py, str(path), base],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )

        stdout = result.stdout or ""
        stderr = result.stderr or ""
        if stdout:
            print(stdout, end="" if stdout.endswith("\n") else "\n")
        if stderr:
            print(stderr, end="" if stderr.endswith("\n") else "\n", file=sys.stderr)

        skipped_keys = _extract_skipped_keys(stdout, stderr)
        script_level_skipped = _is_script_level_skipped(skipped_keys)

        if result.returncode != 0:
            failed.append(script)
            print(f"release_suite_failed={script}", file=sys.stderr)
            break

        if script_level_skipped:
            skipped.append(script)
            print(f"release_suite_item=skipped(remote-safe) script={script}")
        else:
            passed.append(script)
            if skipped_keys:
                print(
                    "release_suite_item=passed script=%s skipped(remote-safe)=%s"
                    % (script, ",".join(skipped_keys))
                )
            else:
                print(f"release_suite_item=passed script={script}")

    if failed:
        print(
            "release_suite_summary=failed passed=%d skipped=%d failed=%d"
            % (len(passed), len(skipped), len(failed)),
            file=sys.stderr,
        )
        return 1

    print(
        "release_suite_summary=ok passed=%d skipped=%d failed=0"
        % (len(passed), len(skipped)),
        flush=True,
    )
    print("release_suite_ok=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
