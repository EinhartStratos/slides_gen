from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os


ROOT_DIR = Path(__file__).resolve().parents[2]
RUNTIME_DIR = ROOT_DIR / "runtime"


@dataclass(slots=True)
class Settings:
    app_name: str
    app_env: str
    api_prefix: str
    runtime_dir: Path
    mock_ftp_dir: Path
    default_template_file: Path
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_schema: str
    ftp_host: str
    ftp_port: int
    ftp_user: str
    ftp_password: str
    ftp_root_dir: str
    default_template_id: str | None
    ppt_master_scripts_dir: Path
    llm_base_url: str
    llm_model: str
    llm_timeout_seconds: int


def _parse_env_file() -> dict[str, list[str]]:
    candidates = [ROOT_DIR / ".env", Path.cwd() / ".env"]
    payload: dict[str, list[str]] = {}
    env_path = next((path for path in candidates if path.exists()), None)
    if env_path is None:
        return payload
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] == value[-1:] and value[:1] in {'"', "'"}:
            value = value[1:-1]
        payload.setdefault(key, []).append(value)
    return payload


def _pick_env(occurrences: dict[str, list[str]], key: str, default: str = "", index: int = 0) -> str:
    if key in os.environ and os.environ[key] != "":
        return os.environ[key]
    values = occurrences.get(key, [])
    if len(values) > index:
        return values[index]
    return default


def _pick_fallback(occurrences: dict[str, list[str]], primary: str, fallback_key: str, fallback_index: int, default: str) -> str:
    value = _pick_env(occurrences, primary, "")
    if value:
        return value
    values = occurrences.get(fallback_key, [])
    if len(values) > fallback_index:
        return values[fallback_index]
    return default


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    occurrences = _parse_env_file()
    db_port_raw = _pick_env(occurrences, "MYSQL_PORT", _pick_env(occurrences, "DB_PORT", "3306"))
    ftp_port_raw = _pick_fallback(occurrences, "FTP_PORT", "DB_PORT", 1, "21")
    ftp_user = _pick_fallback(occurrences, "FTP_USER", "DB_USER", 1, "")
    mock_ftp_dir_raw = _pick_env(occurrences, "MOCK_FTP_DIR", "mock_ftp")
    mock_ftp_dir = Path(mock_ftp_dir_raw)
    if not mock_ftp_dir.is_absolute():
        mock_ftp_dir = ROOT_DIR / mock_ftp_dir
    default_template_file_raw = _pick_env(occurrences, "DEFAULT_TEMPLATE_FILE", "templete.pptx")
    default_template_file = Path(default_template_file_raw)
    if not default_template_file.is_absolute():
        default_template_file = ROOT_DIR / default_template_file
    return Settings(
        app_name=_pick_env(occurrences, "APP_NAME", "slides_gen_server"),
        app_env=_pick_env(occurrences, "APP_ENV", "dev"),
        api_prefix=_pick_env(occurrences, "API_PREFIX", "/api/v1"),
        runtime_dir=RUNTIME_DIR,
        mock_ftp_dir=mock_ftp_dir,
        default_template_file=default_template_file,
        db_host=_pick_env(occurrences, "MYSQL_HOST", _pick_env(occurrences, "DB_HOST", "127.0.0.1")),
        db_port=int(db_port_raw or "3306"),
        db_user=_pick_env(occurrences, "MYSQL_USER", _pick_env(occurrences, "DB_USER", "root")),
        db_password=_pick_env(occurrences, "MYSQL_PASSWORD", _pick_env(occurrences, "DB_PASSWORD", "")),
        db_schema=_pick_env(occurrences, "MYSQL_DATABASE", _pick_env(occurrences, "DB_SCHEMA", "slides_gen_server")),
        ftp_host=_pick_env(occurrences, "FTP_HOST", ""),
        ftp_port=int(ftp_port_raw or "21"),
        ftp_user=ftp_user,
        ftp_password=_pick_env(occurrences, "FTP_PASSWORD", ""),
        ftp_root_dir=_pick_env(occurrences, "FTP_ROOT_DIR", "/slides_gen_server"),
        default_template_id=_pick_env(occurrences, "DEFAULT_TEMPLATE_ID", "") or None,
        ppt_master_scripts_dir=ROOT_DIR / "app" / "vendor" / "ppt_master" / "scripts",
        llm_base_url=_pick_env(occurrences, "LLM_BASE_URL", _pick_env(occurrences, "HOST", "")).rstrip("/"),
        llm_model=_pick_env(occurrences, "LLM_MODEL", _pick_env(occurrences, "BASIC_MODEL", "")),
        llm_timeout_seconds=int(_pick_env(occurrences, "LLM_TIMEOUT_SECONDS", "120") or "120"),
    )
