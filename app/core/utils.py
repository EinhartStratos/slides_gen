from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import secrets
import shutil


def generate_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(4)}"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def json_dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def to_iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
