"""Shared source-row helpers for the indexed C5 identity audit.

This module does not construct a reuse cache.  Cache construction belongs to
identity_cache.py and is keyed by complete SampleIdentity.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def source_rows(path: Path, key: str, label: str):
    data = json.loads(path.read_text())
    rows = []
    for row in data.get(key, []):
        result = row.get("result")
        q = row.get("q", [row.get("qx"), row.get("qy")])
        if result is not None and q[0] is not None and q[1] is not None:
            rows.append({
                "source": label,
                "q": (round(float(q[0]), 10), round(float(q[1]), 10)),
                "result": result,
                "digest": digest(result),
            })
    return rows
