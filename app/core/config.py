from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os

from dotenv import load_dotenv


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
    mock_ftp_enabled: bool
    default_template_id: str | None
    ppt_master_scripts_dir: Path
    llm_base_url: str
    llm_model: str
    llm_timeout_seconds: int


def _get(key: str, default: str = "") -> str:
    val = os.getenv(key)
    if val is not None and val != "":
        return val
    return default


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(ROOT_DIR / ".env", override=False)

    mock_ftp_dir_raw = _get("MOCK_FTP_DIR", "mock_ftp")
    mock_ftp_dir = Path(mock_ftp_dir_raw)
    if not mock_ftp_dir.is_absolute():
        mock_ftp_dir = ROOT_DIR / mock_ftp_dir

    default_template_file_raw = _get("DEFAULT_TEMPLATE_FILE", "templete.pptx")
    default_template_file = Path(default_template_file_raw)
    if not default_template_file.is_absolute():
        default_template_file = ROOT_DIR / default_template_file

    return Settings(
        app_name=_get("APP_NAME", "slides_gen_server"),
        app_env=_get("APP_ENV", "dev"),
        api_prefix=_get("API_PREFIX", "/api/v1"),
        runtime_dir=RUNTIME_DIR,
        mock_ftp_dir=mock_ftp_dir,
        default_template_file=default_template_file,
        db_host=_get("DB_HOST", "127.0.0.1"),
        db_port=int(_get("DB_PORT", "3306") or "3306"),
        db_user=_get("DB_USER", "root"),
        db_password=_get("DB_PASSWORD", ""),
        db_schema=_get("DB_SCHEMA", "slides_gen_server"),
        ftp_host=_get("FTP_HOST", ""),
        ftp_port=int(_get("FTP_PORT", "21") or "21"),
        ftp_user=_get("FTP_USER", ""),
        ftp_password=_get("FTP_PASSWORD", ""),
        ftp_root_dir=_get("FTP_ROOT_DIR", "/slides_gen_server"),
        mock_ftp_enabled=_get("MOCK_FTP_ENABLED", "true").lower() in ("true", "1", "yes"),
        default_template_id=_get("DEFAULT_TEMPLATE_ID", "") or None,
        ppt_master_scripts_dir=ROOT_DIR / "app" / "vendor" / "ppt_master" / "scripts",
        llm_base_url=_get("LLM_BASE_URL", _get("HOST", "")).rstrip("/"),
        llm_model=_get("LLM_MODEL", _get("BASIC_MODEL", "")),
        llm_timeout_seconds=int(_get("LLM_TIMEOUT_SECONDS", "120") or "120"),
    )
