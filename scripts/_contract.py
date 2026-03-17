#!/usr/bin/env python3
"""Release suite contract helpers.

目标：把“必须字段/结构”的判断集中化，避免脚本到处硬编码导致契约抖动。
"""

from __future__ import annotations


def require_keys(label: str, obj: object, keys: list[str]) -> None:
    if not isinstance(obj, dict):
        raise AssertionError(f"{label}: expected dict, got {type(obj).__name__}")
    missing = [k for k in keys if k not in obj]
    if missing:
        raise AssertionError(f"{label}: missing keys: {missing} (have={list(obj.keys())})")


def get_in(obj: object, path: list[object], default=None):
    cur = obj
    for p in path:
        if isinstance(p, int):
            if not isinstance(cur, list) or p < 0 or p >= len(cur):
                return default
            cur = cur[p]
        else:
            if not isinstance(cur, dict) or p not in cur:
                return default
            cur = cur[p]
    return cur

