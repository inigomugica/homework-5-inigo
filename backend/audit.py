"""Append-only audit trail: output/audit_trail.json, one JSON object per line.

The file is only ever opened in append mode, so earlier runs are never wiped.
"""

import json
import threading
from datetime import datetime
from pathlib import Path

from models import AuditEvent

AUDIT_PATH = Path(__file__).resolve().parents[1] / "output" / "audit_trail.json"
MAX_FIELD_CHARS = 2000  # long tool results are clipped so the file stays readable

_lock = threading.Lock()


def _clip(value):
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return value if len(text) <= MAX_FIELD_CHARS else text[:MAX_FIELD_CHARS] + "...[clipped]"


def log(**fields) -> None:
    fields.setdefault("ts", datetime.now().astimezone().isoformat(timespec="seconds"))
    if "detail" in fields:
        fields["detail"] = {k: _clip(v) for k, v in fields["detail"].items()}
    line = AuditEvent(**fields).model_dump_json()
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock, AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
